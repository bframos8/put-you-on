# Maps Spotify's fine-grained genre tags to Bandcamp's 22 canonical genres.
# Order matters: more specific keywords are checked before broader ones.
# First match wins across both the genre list and the keyword list.

KEYWORD_MAP: list[tuple[str, str]] = [
    # hip-hop-rap
    ("hip hop", "hip-hop-rap"),
    ("hip-hop", "hip-hop-rap"),
    ("boom bap", "hip-hop-rap"),
    ("cloud rap", "hip-hop-rap"),
    ("southern hip", "hip-hop-rap"),
    ("gangsta rap", "hip-hop-rap"),
    ("trap", "hip-hop-rap"),
    ("drill", "hip-hop-rap"),
    ("grime", "hip-hop-rap"),
    ("crunk", "hip-hop-rap"),
    ("rap", "hip-hop-rap"),
    # r-b-soul (before "soul" alone)
    ("r&b", "r-b-soul"),
    ("rhythm and blues", "r-b-soul"),
    ("neo soul", "r-b-soul"),
    ("soul", "r-b-soul"),
    # funk
    ("funk", "funk"),
    # jazz
    ("jazz", "jazz"),
    ("bebop", "jazz"),
    ("swing", "jazz"),
    # blues
    ("blues", "blues"),
    # ambient (before "electronic" so ambient-electronic goes here)
    ("ambient", "ambient"),
    ("drone", "ambient"),
    # electronic (more specific before broad)
    ("drum and bass", "electronic"),
    ("dubstep", "electronic"),
    ("techno", "electronic"),
    ("trance", "electronic"),
    ("synthwave", "electronic"),
    ("electronic", "electronic"),
    ("electro", "electronic"),
    ("edm", "electronic"),
    ("house", "electronic"),
    ("club", "electronic"),
    # classical
    ("classical", "classical"),
    ("orchestral", "classical"),
    ("symphony", "classical"),
    ("opera", "classical"),
    ("chamber music", "classical"),
    ("baroque", "classical"),
    # metal (before "rock" so metal subgenres don't fall to rock)
    ("metal", "metal"),
    ("hardcore", "metal"),
    # punk
    ("punk", "punk"),
    ("post-punk", "punk"),
    ("emo", "punk"),
    # rock
    ("rock", "rock"),
    # alternative / indie
    ("alternative", "alternative"),
    ("indie", "alternative"),
    # folk / acoustic
    ("singer-songwriter", "folk"),
    ("folk", "folk"),
    ("acoustic", "acoustic"),
    # country
    ("bluegrass", "country"),
    ("americana", "country"),
    ("country", "country"),
    # reggae (before "dub" so dubstep doesn't land here)
    ("reggae", "reggae"),
    ("dancehall", "reggae"),
    ("ska", "reggae"),
    ("dub", "reggae"),
    # latin
    ("reggaeton", "latin"),
    ("bossa nova", "latin"),
    ("cumbia", "latin"),
    ("salsa", "latin"),
    ("samba", "latin"),
    ("latin", "latin"),
    # world
    ("afrobeat", "world"),
    ("afro-", "world"),
    ("world music", "world"),
    ("world", "world"),
    # experimental
    ("avant-garde", "experimental"),
    ("experimental", "experimental"),
    ("noise", "experimental"),
    ("abstract", "experimental"),
    # soundtrack
    ("film score", "soundtrack"),
    ("video game music", "soundtrack"),
    ("soundtrack", "soundtrack"),
    # pop (broad, last so it doesn't swallow subgenres)
    ("k-pop", "pop"),
    ("j-pop", "pop"),
    ("pop", "pop"),
]


def normalize_genre(spotify_genres: list[str]) -> str | None:
    """Map a list of Spotify genre tags to the closest canonical Bandcamp genre.

    Iterates the genre list in order, and for each genre checks keywords in
    KEYWORD_MAP order. Returns the canonical genre for the first keyword match,
    or None if nothing matches.
    """
    for genre in spotify_genres:
        genre_lower = genre.lower()
        for keyword, canonical in KEYWORD_MAP:
            if keyword in genre_lower:
                return canonical
    return None
