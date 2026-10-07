"""Reading tags out of MusicBrainz.

Search hits carry their tags inline, so a track costs one request and an artist costs
one request. That is the difference between tagging a library in twenty minutes and
tagging it in an hour, at MusicBrainz's one-request-per-second rate.

Tag counts are net votes: 18 means well agreed, 1 means one person, 0 means it was
voted back down. They become source weights in :func:`weigh`.

Counts are only meaningful *relative to the entity they are on*: a well known artist
collects tens of votes on its main genre, an obscure one collects one vote on a tag that
is just as correct. So :func:`weigh` scales by the entity's own top tag rather than by an
absolute threshold.
"""

from __future__ import annotations

import re
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings
from app.integrations.musicbrainz.client import MusicBrainzClient
from app.integrations.musicbrainz.errors import MusicBrainzError

#: How many tags to keep per entity, by vote. Anyone can tag anything on MusicBrainz, so
#: a popular artist grows a long tail of one-voter tags that says nothing about the music
#: (Metallica, live: 65 tags, of which four carry more than seven votes).
TOP_TAGS = 8

SEARCH_LIMIT = 3

#: Lucene reserves these. Titles genuinely contain most of them.
_LUCENE = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')

ModelT = TypeVar("ModelT", bound=BaseModel)


def escape(value: str) -> str:
    """Escape a value for a Lucene phrase query."""
    return _LUCENE.sub(r"\\\1", value)


class MusicBrainzModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Tag(MusicBrainzModel):
    name: str
    #: Net votes. Can be 0 (or absent on some entities), which means "not agreed".
    count: int = 0


class ArtistRef(MusicBrainzModel):
    id: str | None = None
    name: str | None = None


class ArtistCredit(MusicBrainzModel):
    name: str | None = None
    artist: ArtistRef | None = None


class Recording(MusicBrainzModel):
    """A hit from ``GET /recording?query=``."""

    id: str
    title: str | None = None
    #: Lucene relevance, 0-100. Anything below ``musicbrainz_min_score`` is a guess.
    score: int = 0
    tags: list[Tag] = Field(default_factory=list)
    artist_credit: list[ArtistCredit] = Field(default_factory=list, alias="artist-credit")

    @property
    def artist_names(self) -> list[str]:
        return [
            credit.artist.name
            for credit in self.artist_credit
            if credit.artist and credit.artist.name
        ]


class RecordingSearch(MusicBrainzModel):
    count: int = 0
    recordings: list[Recording] = Field(default_factory=list)


class SearchedArtist(MusicBrainzModel):
    """A hit from ``GET /artist?query=``."""

    id: str
    name: str | None = None
    score: int = 0
    tags: list[Tag] = Field(default_factory=list)


class ArtistSearch(MusicBrainzModel):
    count: int = 0
    artists: list[SearchedArtist] = Field(default_factory=list)


def _parse(model: type[ModelT], payload: Any, what: str) -> ModelT:
    """Turn an unusable body into a typed error, so one bad response costs one track."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise MusicBrainzError(f"MusicBrainz returned a {what} we could not read") from exc


def weigh(tags: list[Tag]) -> list[tuple[str, float]]:
    """Turn net votes into 0-1 source weights, strongest first.

    Weights are relative to the entity's own top tag, so its most agreed tag always
    arrives at 1.0 and the rest are ranked against it. An absolute threshold instead
    would read a one-vote artist as "we know nothing" when in fact its single tag is the
    consensus, and would read the long tail on a famous artist as meaningful.

    Downvoted tags (count <= 0) are dropped rather than trusted at a floor: the whole
    point of the vote count is that the community disagreed with them.
    """
    voted = sorted((tag for tag in tags if tag.count > 0), key=lambda tag: -tag.count)
    if not voted:
        return []
    top = voted[0].count
    return [(tag.name, round(tag.count / top, 3)) for tag in voted[:TOP_TAGS]]


async def search_recording(
    client: MusicBrainzClient, *, title: str, artist: str | None = None, limit: int = SEARCH_LIMIT
) -> RecordingSearch:
    terms = [f'recording:"{escape(title)}"']
    if artist:
        terms.append(f'artist:"{escape(artist)}"')
    payload = await client.get_json(
        "/recording", params={"query": " AND ".join(terms), "fmt": "json", "limit": limit}
    )
    return _parse(RecordingSearch, payload or {}, "recording search")


async def search_artist(
    client: MusicBrainzClient, *, name: str, limit: int = SEARCH_LIMIT
) -> ArtistSearch:
    payload = await client.get_json(
        "/artist", params={"query": f'artist:"{escape(name)}"', "fmt": "json", "limit": limit}
    )
    return _parse(ArtistSearch, payload or {}, "artist search")


async def recording_tags(
    client: MusicBrainzClient, *, title: str, artist: str | None = None
) -> list[tuple[str, float]]:
    """Tags for one recording, or ``[]`` when nothing matches confidently.

    A miss is not an error: MusicBrainz simply does not have every track, and a
    low-scoring hit is a different song with a similar name.
    """
    search = await search_recording(client, title=title, artist=artist)
    for hit in search.recordings:
        if hit.score >= settings.musicbrainz_min_score:
            return weigh(hit.tags)
        break  # hits are score-ordered, so the first miss ends it
    return []


async def artist_tags(client: MusicBrainzClient, *, name: str) -> list[tuple[str, float]]:
    """Tags for an artist, or ``[]``. Denser than recording tags in practice."""
    search = await search_artist(client, name=name)
    for hit in search.artists:
        if hit.score >= settings.musicbrainz_min_score:
            return weigh(hit.tags)
        break
    return []
