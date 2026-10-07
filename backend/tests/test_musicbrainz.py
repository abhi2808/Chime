"""MusicBrainz integration: query building, tag weighting, misses, failures.

Fixtures copy the shapes verified live on 2026-09-21 (see the module docstring in
``app/integrations/musicbrainz/client.py``): search hits carry ``score`` and inline
``tags``, tag counts are net votes and may be 0, and a miss is ``count: 0``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from app.core.config import settings
from app.integrations.musicbrainz import (
    API_BASE,
    MusicBrainzClient,
    MusicBrainzError,
    MusicBrainzServerError,
)
from app.integrations.musicbrainz import tags as mb

RECORDING_URL = f"{API_BASE}/recording"
ARTIST_URL = f"{API_BASE}/artist"


def recordings(*hits: dict[str, Any]) -> dict[str, Any]:
    return {"count": len(hits), "offset": 0, "recordings": list(hits)}


def hit(*, score: int = 100, tags: list[tuple[str, int]] | None = None) -> dict[str, Any]:
    return {
        "id": "rec-1",
        "title": "A Song",
        "score": score,
        "tags": [{"name": name, "count": count} for name, count in (tags or [])],
        "artist-credit": [{"name": "A Band", "artist": {"id": "art-1", "name": "A Band"}}],
    }


@pytest.fixture
def mb_client() -> MusicBrainzClient:
    return MusicBrainzClient(client=httpx.AsyncClient(), sleep=_no_sleep)


async def _no_sleep(_seconds: float) -> None:
    return None


class TestQueries:
    def test_lucene_specials_are_escaped(self) -> None:
        assert mb.escape('A "Song" (Remix)') == r"A \"Song\" \(Remix\)"
        assert mb.escape("AC/DC") == r"AC\/DC"
        assert mb.escape("2 + 2") == r"2 \+ 2"

    @respx.mock
    async def test_a_recording_query_pairs_title_with_artist(
        self, mb_client: MusicBrainzClient
    ) -> None:
        route = respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(200, json=recordings(hit()))
        )
        await mb.search_recording(mb_client, title="A Song", artist="A Band")

        params = route.calls[0].request.url.params
        assert params["query"] == 'recording:"A Song" AND artist:"A Band"'
        assert params["fmt"] == "json"
        assert params["limit"] == str(mb.SEARCH_LIMIT)

    @respx.mock
    async def test_the_artist_term_is_dropped_when_we_do_not_know_it(
        self, mb_client: MusicBrainzClient
    ) -> None:
        route = respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(200, json=recordings(hit()))
        )
        await mb.search_recording(mb_client, title="A Song")
        assert route.calls[0].request.url.params["query"] == 'recording:"A Song"'

    @respx.mock
    async def test_every_call_identifies_itself_and_sends_no_credentials(
        self, mb_client: MusicBrainzClient
    ) -> None:
        """MusicBrainz blocks unidentified clients, and there is no token to leak."""
        route = respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(200, json=recordings())
        )
        await mb.search_recording(mb_client, title="A Song")

        headers = route.calls[0].request.headers
        assert settings.musicbrainz_agent in headers["user-agent"]
        assert "authorization" not in headers


class TestWeighting:
    def test_net_votes_become_weights_strongest_first(self) -> None:
        weighted = mb.weigh(
            [mb.Tag(name="rock", count=3), mb.Tag(name="downtempo", count=12)]
        )
        assert weighted[0] == ("downtempo", 1.0)
        assert weighted[1] == ("rock", pytest.approx(0.25))

    def test_weights_are_relative_to_the_entity_not_absolute(self) -> None:
        """An obscure artist's single vote is still its consensus (Marconi Union, live:
        two votes on "ambient"). An absolute threshold would read that as ignorance."""
        obscure = mb.weigh([mb.Tag(name="ambient", count=2), mb.Tag(name="post rock", count=1)])
        famous = mb.weigh([mb.Tag(name="rock", count=43), mb.Tag(name="glam rock", count=24)])
        assert obscure[0][1] == 1.0
        assert famous[0][1] == 1.0
        assert obscure[1][1] == pytest.approx(0.5)

    def test_the_long_tail_is_cut_off(self) -> None:
        """Anyone can tag anything, so a famous artist grows dozens of stray tags."""
        tags = [mb.Tag(name=f"tag {index}", count=40 - index) for index in range(30)]
        assert len(mb.weigh(tags)) == mb.TOP_TAGS

    def test_downvoted_tags_are_dropped(self) -> None:
        assert mb.weigh([mb.Tag(name="a", count=0), mb.Tag(name="b", count=-2)]) == []


class TestRecordingTags:
    @respx.mock
    async def test_a_confident_hit_returns_weighted_tags(
        self, mb_client: MusicBrainzClient
    ) -> None:
        respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(
                200, json=recordings(hit(score=100, tags=[("trip hop", 4), ("ambient", 1)]))
            )
        )
        pairs = await mb.recording_tags(mb_client, title="A Song", artist="A Band")
        assert pairs == [("trip hop", 1.0), ("ambient", pytest.approx(0.25))]

    @respx.mock
    async def test_a_low_scoring_hit_is_a_different_song(
        self, mb_client: MusicBrainzClient
    ) -> None:
        respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(
                200, json=recordings(hit(score=55, tags=[("techno", 9)]))
            )
        )
        assert await mb.recording_tags(mb_client, title="A Song") == []

    @respx.mock
    async def test_a_miss_is_empty_not_an_error(self, mb_client: MusicBrainzClient) -> None:
        respx.get(RECORDING_URL).mock(return_value=httpx.Response(200, json=recordings()))
        assert await mb.recording_tags(mb_client, title="Nothing") == []

    @respx.mock
    async def test_a_hit_with_no_tags_is_empty(self, mb_client: MusicBrainzClient) -> None:
        respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(200, json=recordings(hit(tags=[])))
        )
        assert await mb.recording_tags(mb_client, title="A Song") == []

    @respx.mock
    async def test_artist_tags_come_from_the_artist_search(
        self, mb_client: MusicBrainzClient
    ) -> None:
        respx.get(ARTIST_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "count": 1,
                    "artists": [
                        {
                            "id": "art-1",
                            "name": "A Band",
                            "score": 100,
                            "tags": [{"name": "electronic", "count": 18}],
                        }
                    ],
                },
            )
        )
        assert await mb.artist_tags(mb_client, name="A Band") == [("electronic", 1.0)]


class TestFailures:
    @respx.mock
    async def test_a_body_we_cannot_read_is_a_typed_error(
        self, mb_client: MusicBrainzClient
    ) -> None:
        respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(200, json={"recordings": "not a list"})
        )
        with pytest.raises(MusicBrainzError, match="could not read"):
            await mb.search_recording(mb_client, title="A Song")

    @respx.mock
    async def test_throttling_arrives_as_503_and_is_retried(
        self, mb_client: MusicBrainzClient
    ) -> None:
        """MusicBrainz answers a too-fast caller with 503, not 429."""
        route = respx.get(RECORDING_URL).mock(
            side_effect=[
                httpx.Response(503, text="rate limit exceeded"),
                httpx.Response(200, json=recordings(hit(tags=[("house", 5)]))),
            ]
        )
        assert await mb.recording_tags(mb_client, title="A Song") == [("house", 1.0)]
        assert route.call_count == 2

    @respx.mock
    async def test_a_server_that_never_recovers_raises(
        self, mb_client: MusicBrainzClient
    ) -> None:
        respx.get(RECORDING_URL).mock(return_value=httpx.Response(503))
        with pytest.raises(MusicBrainzServerError):
            await mb.search_recording(mb_client, title="A Song")
