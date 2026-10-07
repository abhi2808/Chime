"""The job that walks a library through a tag source."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.musicbrainz import API_BASE, MusicBrainzClient, MusicBrainzError
from app.models import Artist, Track, TrackTag, User, UserTrack
from app.models.track_tag import SOURCE_EXTERNAL, SOURCE_MANUAL, SOURCE_UNKNOWN
from app.services.tagging import NOTHING, SourceTags, TagMap, compute
from app.services.track_tagger import (
    MusicBrainzTagSource,
    SpotifyGenreTagSource,
    TagRun,
    store,
    tag_tracks,
    unknown_tracks,
    untagged_tracks,
)

RECORDING_URL = f"{API_BASE}/recording"
ARTIST_URL = f"{API_BASE}/artist"

MAP = TagMap.from_data(
    {
        "tags": {
            "ambient": {"energy": 1, "calm": 0.9},
            "techno": {"energy": 4.5, "workout": 0.9},
        }
    }
)


async def _no_sleep(_seconds: float) -> None:
    return None


def make_track(db: Session, user: User, name: str, artist: str, *, liked_days_ago: int = 0) -> Track:
    track = Track(
        spotify_track_id=f"t-{name}",
        name=name,
        artist_ids=[f"a-{artist}"],
        artist_names=[artist],
    )
    db.add(track)
    db.flush()
    db.add(
        UserTrack(
            user_id=user.id,
            track_id=track.id,
            source="liked",
            liked_at=datetime.now(timezone.utc) - timedelta(days=liked_days_ago),
        )
    )
    db.commit()
    return track


class Stub:
    """A tag source with no network, to test the loop rather than MusicBrainz."""

    name = SOURCE_EXTERNAL

    def __init__(self, answers: dict[str, SourceTags], fail_on: str | None = None) -> None:
        self._answers = answers
        self._fail_on = fail_on
        self.asked: list[tuple[str, str | None]] = []

    async def tags_for(self, *, title: str, artist: str | None = None) -> SourceTags:
        self.asked.append((title, artist))
        if title == self._fail_on:
            raise MusicBrainzError("MusicBrainz fell over")
        return self._answers.get(title, NOTHING)


class TestSelection:
    def test_only_untagged_liked_tracks_are_picked_up(self, db: Session, user: User) -> None:
        first = make_track(db, user, "Quiet", "Someone", liked_days_ago=1)
        second = make_track(db, user, "Loud", "Someone Else", liked_days_ago=2)
        db.add(TrackTag(track_id=first.id, energy=2.0, affinities={}))
        db.commit()

        assert [track.id for track in untagged_tracks(db, user.id)] == [second.id]

    def test_newest_liked_first(self, db: Session, user: User) -> None:
        older = make_track(db, user, "Older", "A", liked_days_ago=10)
        newer = make_track(db, user, "Newer", "B", liked_days_ago=1)
        assert [track.id for track in untagged_tracks(db, user.id)] == [newer.id, older.id]

    def test_another_users_library_is_not_touched(self, db: Session, user: User) -> None:
        make_track(db, user, "Mine", "A")
        other = User(spotify_account_id="acc2", spotify_user_id="other", display_name="Other")
        db.add(other)
        db.commit()
        assert untagged_tracks(db, other.id) == []


class TestStoring:
    def test_a_tag_row_records_the_breakdown_and_the_raw_tags(
        self, db: Session, user: User
    ) -> None:
        track = make_track(db, user, "Quiet", "A")
        store(db, track.id, compute([("ambient", 1.0)], MAP), SOURCE_EXTERNAL)
        db.commit()

        row = db.scalar(select(TrackTag).where(TrackTag.track_id == track.id))
        assert row is not None
        assert row.energy == 1.0
        assert row.affinities == {"calm": 0.9}
        assert row.source == SOURCE_EXTERNAL
        assert row.confidence > 0
        assert row.raw_tags == [["ambient", 1.0]]

    def test_a_track_the_map_does_not_know_is_stored_as_unknown(
        self, db: Session, user: User
    ) -> None:
        """So a second run can tell "we looked and failed" from "we never looked"."""
        track = make_track(db, user, "Odd", "A")
        store(db, track.id, compute([("witch house", 1.0)], MAP), SOURCE_EXTERNAL)
        db.commit()

        row = db.scalar(select(TrackTag).where(TrackTag.track_id == track.id))
        assert row is not None
        assert row.source == SOURCE_UNKNOWN
        assert row.energy == 3.0
        assert row.confidence == 0.0
        assert row.raw_tags == [["witch house", 1.0]]

    def test_a_manual_tag_is_never_overwritten(self, db: Session, user: User) -> None:
        track = make_track(db, user, "Quiet", "A")
        db.add(
            TrackTag(
                track_id=track.id, energy=5.0, affinities={}, source=SOURCE_MANUAL, confidence=1.0
            )
        )
        db.commit()

        assert store(db, track.id, compute([("ambient", 1.0)], MAP), SOURCE_EXTERNAL) is None
        db.commit()
        row = db.scalar(select(TrackTag).where(TrackTag.track_id == track.id))
        assert row is not None
        assert row.energy == 5.0
        assert row.source == SOURCE_MANUAL

    def test_a_later_run_replaces_an_automatic_tag(self, db: Session, user: User) -> None:
        track = make_track(db, user, "Quiet", "A")
        store(db, track.id, compute([("witch house", 1.0)], MAP), SOURCE_EXTERNAL)
        db.commit()
        store(db, track.id, compute([("techno", 1.0)], MAP), SOURCE_EXTERNAL)
        db.commit()

        rows = db.scalars(select(TrackTag).where(TrackTag.track_id == track.id)).all()
        assert len(rows) == 1
        assert rows[0].energy == 4.5


class TestRun:
    async def test_it_counts_what_happened_without_naming_anything(
        self, db: Session, user: User
    ) -> None:
        quiet = make_track(db, user, "Quiet", "A", liked_days_ago=1)
        loud = make_track(db, user, "Loud", "B", liked_days_ago=2)
        odd = make_track(db, user, "Odd", "C", liked_days_ago=3)
        absent = make_track(db, user, "Absent", "D", liked_days_ago=4)

        source = Stub(
            {
                "Quiet": SourceTags(pairs=(("ambient", 1.0),), via="recording"),
                "Loud": SourceTags(pairs=(("techno", 1.0),), via="artist"),
                "Odd": SourceTags(pairs=(("witch house", 1.0),), via="recording"),
            }
        )
        run = await tag_tracks(db, untagged_tracks(db, user.id), source, tag_map=MAP)

        assert run.considered == 4
        assert run.tagged == 2
        assert run.unmapped == 1
        assert run.missing == 1
        assert run.via == {"recording": 2, "artist": 1}
        assert run.unmatched == {"witch house": 1}
        assert run.coverage == 0.5
        assert sorted(run.energy) == [1.0, 4.5]
        # Every track that was looked up got a row: the unmapped one, and the one the
        # source had never heard of. Both are "we looked", which is worth recording.
        assert {row.track_id for row in db.scalars(select(TrackTag)).all()} == {
            quiet.id,
            loud.id,
            odd.id,
            absent.id,
        }

    async def test_a_track_the_source_has_never_heard_of_is_recorded_as_looked_at(
        self, db: Session, user: User
    ) -> None:
        """SPEC section 4: unknown means "we looked and found nothing", which a later run
        has to tell apart from "never looked" — otherwise 12% of a real library is
        re-queried at 1.8 s each, every run, forever."""
        track = make_track(db, user, "Absent", "A")

        run = await tag_tracks(db, [track], Stub({}), tag_map=MAP)

        assert run.missing == 1
        row = db.scalar(select(TrackTag).where(TrackTag.track_id == track.id))
        assert row is not None
        assert row.source == SOURCE_UNKNOWN
        assert row.confidence == 0.0
        assert row.raw_tags is None
        # So the next ordinary run leaves it alone, and only --retry-unknown picks it up.
        assert untagged_tracks(db, user.id) == []
        assert [found.id for found in unknown_tracks(db, user.id)] == [track.id]

    async def test_a_dry_run_records_no_unknowns_either(self, db: Session, user: User) -> None:
        track = make_track(db, user, "Absent", "A")
        run = await tag_tracks(db, [track], Stub({}), tag_map=MAP, persist=False)
        assert run.missing == 1
        assert db.scalars(select(TrackTag)).all() == []

    async def test_re_checking_an_unknown_track_upgrades_it(
        self, db: Session, user: User
    ) -> None:
        """The point of keeping the row: MusicBrainz grows, so a miss is not forever."""
        track = make_track(db, user, "Quiet", "A")
        await tag_tracks(db, [track], Stub({}), tag_map=MAP)

        source = Stub({"Quiet": SourceTags(pairs=(("ambient", 1.0),), via="recording")})
        await tag_tracks(db, unknown_tracks(db, user.id), source, tag_map=MAP)

        rows = db.scalars(select(TrackTag).where(TrackTag.track_id == track.id)).all()
        assert len(rows) == 1
        assert rows[0].source == SOURCE_EXTERNAL
        assert rows[0].energy == 1.0
        assert unknown_tracks(db, user.id) == []

    async def test_one_failure_does_not_lose_the_rest_of_the_run(
        self, db: Session, user: User
    ) -> None:
        make_track(db, user, "Quiet", "A", liked_days_ago=1)
        make_track(db, user, "Broken", "B", liked_days_ago=2)
        make_track(db, user, "Loud", "C", liked_days_ago=3)

        source = Stub(
            {
                "Quiet": SourceTags(pairs=(("ambient", 1.0),), via="recording"),
                "Loud": SourceTags(pairs=(("techno", 1.0),), via="recording"),
            },
            fail_on="Broken",
        )
        run = await tag_tracks(db, untagged_tracks(db, user.id), source, tag_map=MAP)

        assert run.failed == 1
        assert run.tagged == 2
        assert len(db.scalars(select(TrackTag)).all()) == 2

    async def test_the_first_credited_artist_is_the_one_we_ask_about(
        self, db: Session, user: User
    ) -> None:
        track = make_track(db, user, "Quiet", "A")
        track.artist_names = ["A", "Guest"]
        db.commit()

        source = Stub({})
        await tag_tracks(db, [track], source, tag_map=MAP)
        assert source.asked == [("Quiet", "A")]

    async def test_progress_is_reported_once_per_track_whatever_happened(
        self, db: Session, user: User
    ) -> None:
        """A half-hour job that prints nothing looks exactly like a hung one, so the
        callback has to fire on misses and failures too, not only on successes."""
        make_track(db, user, "Quiet", "A", liked_days_ago=1)
        make_track(db, user, "Absent", "B", liked_days_ago=2)
        make_track(db, user, "Broken", "C", liked_days_ago=3)

        source = Stub(
            {"Quiet": SourceTags(pairs=(("ambient", 1.0),), via="recording")},
            fail_on="Broken",
        )
        seen: list[tuple[int, int, int, int]] = []
        await tag_tracks(
            db,
            untagged_tracks(db, user.id),
            source,
            tag_map=MAP,
            on_progress=lambda run: seen.append(
                (run.considered, run.tagged, run.missing, run.failed)
            ),
        )

        assert seen == [(1, 1, 0, 0), (2, 1, 1, 0), (3, 1, 1, 1)]

    async def test_a_caller_owned_run_survives_an_interrupt(
        self, db: Session, user: User
    ) -> None:
        """Ctrl+C on track 300 of 1000 has still tagged 299 tracks. The caller keeps the
        tally so it can say so, and every row before the stop is already committed."""
        make_track(db, user, "Quiet", "A", liked_days_ago=1)
        make_track(db, user, "Stop", "B", liked_days_ago=2)
        make_track(db, user, "Never", "C", liked_days_ago=3)

        class Interrupting(Stub):
            async def tags_for(self, *, title: str, artist: str | None = None) -> SourceTags:
                if title == "Stop":
                    raise KeyboardInterrupt
                return await super().tags_for(title=title, artist=artist)

        source = Interrupting({"Quiet": SourceTags(pairs=(("ambient", 1.0),), via="recording")})
        run = TagRun()
        with pytest.raises(KeyboardInterrupt):
            await tag_tracks(db, untagged_tracks(db, user.id), source, tag_map=MAP, run=run)

        assert (run.considered, run.tagged) == (2, 1)
        assert len(db.scalars(select(TrackTag)).all()) == 1
        # And the next run picks up exactly what is left.
        assert len(untagged_tracks(db, user.id)) == 2

    async def test_a_dry_run_writes_nothing(self, db: Session, user: User) -> None:
        track = make_track(db, user, "Quiet", "A")
        source = Stub({"Quiet": SourceTags(pairs=(("ambient", 1.0),), via="recording")})

        run = await tag_tracks(db, [track], source, tag_map=MAP, persist=False)
        assert run.tagged == 1
        assert db.scalars(select(TrackTag)).all() == []


class TestMusicBrainzSource:
    @respx.mock
    async def test_it_falls_back_to_the_artist_and_caches_that_answer(self) -> None:
        """A 30-track artist must cost one artist lookup, not thirty."""
        recording = respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(200, json={"count": 0, "recordings": []})
        )
        artist = respx.get(ARTIST_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "count": 1,
                    "artists": [
                        {
                            "id": "art-1",
                            "name": "A Band",
                            "score": 100,
                            "tags": [{"name": "techno", "count": 9}],
                        }
                    ],
                },
            )
        )
        source = MusicBrainzTagSource(MusicBrainzClient(client=httpx.AsyncClient(), sleep=_no_sleep))

        first = await source.tags_for(title="One", artist="A Band")
        second = await source.tags_for(title="Two", artist="A Band")

        assert first.via == "artist"
        assert second.pairs == first.pairs == (("techno", 1.0),)
        assert recording.call_count == 2
        assert artist.call_count == 1

    @respx.mock
    async def test_a_recording_hit_skips_the_artist_lookup(self) -> None:
        respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "count": 1,
                    "recordings": [
                        {
                            "id": "rec-1",
                            "title": "One",
                            "score": 100,
                            "tags": [{"name": "ambient", "count": 5}],
                        }
                    ],
                },
            )
        )
        artist = respx.get(ARTIST_URL).mock(return_value=httpx.Response(200, json={}))
        source = MusicBrainzTagSource(MusicBrainzClient(client=httpx.AsyncClient(), sleep=_no_sleep))

        found = await source.tags_for(title="One", artist="A Band")
        assert found.via == "recording"
        assert artist.call_count == 0

    @respx.mock
    async def test_the_fallback_can_be_turned_off(self) -> None:
        respx.get(RECORDING_URL).mock(
            return_value=httpx.Response(200, json={"count": 0, "recordings": []})
        )
        artist = respx.get(ARTIST_URL).mock(return_value=httpx.Response(200, json={}))
        source = MusicBrainzTagSource(
            MusicBrainzClient(client=httpx.AsyncClient(), sleep=_no_sleep), artist_fallback=False
        )

        assert await source.tags_for(title="One", artist="A Band") is NOTHING
        assert artist.call_count == 0


class TestSpotifyGenreSource:
    @respx.mock
    async def test_it_reads_cached_genres_and_never_calls_out(self, db: Session) -> None:
        db.add(Artist(spotify_artist_id="a-1", name="A Band", genres=["ambient", "techno"]))
        db.commit()

        found = await SpotifyGenreTagSource(db).tags_for(title="One", artist="A Band")
        assert found.via == "genres"
        assert found.pairs == (("ambient", 1.0), ("techno", 1.0))

    @respx.mock
    async def test_an_artist_spotify_sent_no_genres_for_yields_nothing(
        self, db: Session
    ) -> None:
        """Which is every artist on this app: Spotify has stopped sending the field."""
        db.add(Artist(spotify_artist_id="a-1", name="A Band", genres=None))
        db.commit()

        assert await SpotifyGenreTagSource(db).tags_for(title="One", artist="A Band") is NOTHING

    @respx.mock
    async def test_an_unknown_artist_yields_nothing(self, db: Session) -> None:
        assert await SpotifyGenreTagSource(db).tags_for(title="One", artist="Nobody") is NOTHING


@pytest.mark.parametrize("weight", [0.0, 1.0])
def test_a_source_weight_of_zero_still_records_the_raw_tag(weight: float) -> None:
    """So an edited map can be re-applied later without re-fetching anything."""
    assert compute([("ambient", weight)], MAP).raw == (("ambient", weight),)
