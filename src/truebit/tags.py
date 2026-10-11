# `truebit tags`: see every tag in a file (title, artist, album, cover art...) and change
# them for good.
#
# Each format keeps its tags somewhere different:
#   MP3, WAV, AIFF, TTA    an ID3 tag
#   FLAC, OGG, Opus        "Vorbis comments"
#   M4A, M4B, MP4          iTunes-style atoms
#   WMA                    ASF attributes
#   APE, WavPack           an APEv2 tag
# The mutagen library reads and writes all of them. It rewrites ONLY the tag: the audio is
# never decoded or re-encoded, so changing tags can't change the sound.

import base64
import shutil
from pathlib import Path

from mutagen import File as open_with_mutagen
from mutagen.aiff import AIFF
from mutagen.apev2 import APEv2File
from mutagen.asf import ASF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, COMM, TXXX, Frames
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.trueaudio import TrueAudio
from mutagen.wave import WAVE

# The tag names TrueBit understands in every format
COMMON_NAMES = ["title", "artist", "album", "albumartist", "year", "genre", "track", "disc", "composer",
                "comment"]

# Other spellings people use for the same tags
NAME_ALIASES = {"date": "year", "tracknumber": "track", "discnumber": "disc", "album_artist": "albumartist",
                "album artist": "albumartist", "description": "comment"}

# What each common name is called inside each kind of tag
ID3_FRAMES = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2", "year": "TDRC",
              "genre": "TCON", "track": "TRCK", "disc": "TPOS", "composer": "TCOM"}  # comment = COMM
VORBIS_KEYS = {"title": "title", "artist": "artist", "album": "album", "albumartist": "albumartist",
               "year": "date", "genre": "genre", "track": "tracknumber", "disc": "discnumber",
               "composer": "composer", "comment": "comment"}
MP4_KEYS = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "albumartist": "aART",
            "year": "\xa9day", "genre": "\xa9gen", "track": "trkn", "disc": "disk", "composer": "\xa9wrt",
            "comment": "\xa9cmt"}
ASF_KEYS = {"title": "Title", "artist": "Author", "album": "WM/AlbumTitle", "albumartist": "WM/AlbumArtist",
            "year": "WM/Year", "genre": "WM/Genre", "track": "WM/TrackNumber", "disc": "WM/PartOfSet",
            "composer": "WM/Composer", "comment": "Description"}
APE_KEYS = {"title": "Title", "artist": "Artist", "album": "Album", "albumartist": "Album Artist",
            "year": "Year", "genre": "Genre", "track": "Track", "disc": "Disc", "composer": "Composer",
            "comment": "Comment"}

# Readable names for other tags you often see
OTHER_NAMES = {"tsse": "encoder", "\xa9too": "encoder", "wm/encodingsettings": "encoder", "tenc": "encoded by",
               "tcop": "copyright", "cprt": "copyright", "tpub": "publisher", "tbpm": "bpm", "tmpo": "bpm",
               "tkey": "key", "tlan": "language", "uslt": "lyrics", "\xa9lyr": "lyrics", "tsrc": "isrc",
               "cpil": "compilation", "tcmp": "compilation", "pgap": "gapless", "rtng": "rating",
               "soar": "sort artist", "sonm": "sort title", "soal": "sort album", "soco": "sort composer"}

FAMILY_NAMES = {"id3": "ID3v2 tag", "vorbis": "Vorbis comments", "mp4": "MP4 (iTunes) tags",
                "asf": "WMA attributes", "ape": "APEv2 tag"}
MP4_FREEFORM = "----:com.apple.iTunes:"  # how M4A files store tags with any other name
OGG_PICTURE_KEY = "metadata_block_picture"


class TagError(Exception):
    pass


# Opens a file with mutagen and works out which kind of tag it uses: (audio, family)
def open_tagged_file(file_path):
    try:
        audio = open_with_mutagen(file_path)
    except Exception as error:
        raise TagError("Can't read the tags: " + str(error))
    if audio is None:
        raise TagError("This file type isn't supported for tags.")

    if isinstance(audio, (MP3, WAVE, AIFF, TrueAudio)):
        family = "id3"
    elif isinstance(audio, (FLAC, OggVorbis, OggOpus)):
        family = "vorbis"
    elif isinstance(audio, MP4):
        family = "mp4"
    elif isinstance(audio, ASF):
        family = "asf"
    elif isinstance(audio, APEv2File):
        family = "ape"
    else:
        raise TagError("This kind of file can't hold tags (raw AAC is one). Save it as M4A first: "
                       "truebit normalize FILE --format m4a")
    return audio, family


# "Date", "TRACKNUMBER", "album artist" -> "year", "track", "albumartist"
def common_name(name):
    name = name.strip().lower()
    return NAME_ALIASES.get(name, name)


# The common name for a key inside a tag (e.g. "TIT2" -> "title"), or the key itself
def name_for_key(family, key):
    tables = {"id3": ID3_FRAMES, "vorbis": VORBIS_KEYS, "mp4": MP4_KEYS, "asf": ASF_KEYS, "ape": APE_KEYS}
    for name, native_key in tables[family].items():
        if native_key.lower() == key.lower():
            return name
    if family == "mp4" and key.startswith(MP4_FREEFORM):
        return key[len(MP4_FREEFORM):]
    return OTHER_NAMES.get(key.lower(), key)


# Makes a FLAC-style picture block (used by FLAC, and inside OGG/Opus files)
def make_picture(data, mime):
    picture = Picture()
    picture.type = 3  # 3 = front cover
    picture.mime = mime
    picture.desc = "Cover"
    picture.data = data
    return picture


# ---- Reading -----------------------------------------------------------------------------

# Every tag as a list of (name, value) rows, skipping the cover (that's reported separately)
def tag_rows(audio, family):
    rows = []
    if audio.tags is None:
        return rows

    if family == "id3":
        for frame in audio.tags.values():
            if frame.FrameID == "APIC":
                continue
            if frame.FrameID == "COMM":
                name = "comment"
            elif frame.FrameID == "TXXX":
                name = frame.desc
            else:
                name = name_for_key(family, frame.FrameID)
            if not hasattr(frame, "text"):
                value = "(data)"
            elif isinstance(frame.text, str):  # lyrics are one long text, not a list
                value = frame.text
            else:
                value = " / ".join(str(text) for text in frame.text)
            rows.append((name, value))

    elif family == "mp4":
        for key, values in audio.tags.items():
            if key == "covr":
                continue
            if not isinstance(values, list):  # yes/no flags like "compilation" are a single value
                values = [values]
            texts = []
            for value in values:
                if isinstance(value, tuple):  # track and disc: (number, total)
                    texts.append(f"{value[0]}/{value[1]}" if value[1] else str(value[0]))
                elif isinstance(value, bytes):
                    texts.append(value.decode("utf-8", errors="replace"))
                else:
                    texts.append(str(value))
            rows.append((name_for_key(family, key), " / ".join(texts)))

    else:  # vorbis, asf, ape: a name -> values dictionary
        for key in audio.tags.keys():
            if key.lower() == OGG_PICTURE_KEY or key == "WM/Picture" or key.lower().startswith("cover art"):
                continue
            values = audio.tags[key]
            if not isinstance(values, list):
                values = [values]
            texts = []
            for value in values:
                texts.append(str(getattr(value, "value", value)))
            rows.append((name_for_key(family, key), " / ".join(texts)))
    return sort_rows(rows)


# Puts the common tags first, in the usual order (title, artist, album...), then the rest
def sort_rows(rows):
    sorted_rows = []
    for name in COMMON_NAMES:
        for row in rows:
            if row[0] == name:
                sorted_rows.append(row)
    for row in rows:
        if row[0] not in COMMON_NAMES:
            sorted_rows.append(row)
    return sorted_rows


# The cover picture: (bytes, mime type), or None
def read_cover(audio, family):
    if family == "vorbis" and isinstance(audio, FLAC):
        if len(audio.pictures) > 0:
            return audio.pictures[0].data, audio.pictures[0].mime
        return None
    if audio.tags is None:
        return None

    if family == "id3":
        pictures = audio.tags.getall("APIC")
        if len(pictures) > 0:
            return pictures[0].data, pictures[0].mime
    elif family == "vorbis":
        encoded = audio.tags.get(OGG_PICTURE_KEY)
        if encoded:
            picture = Picture(base64.b64decode(encoded[0]))
            return picture.data, picture.mime
    elif family == "mp4":
        covers = audio.tags.get("covr")
        if covers:
            mime = "image/png" if covers[0].imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
            return bytes(covers[0]), mime
    return None


# Everything for `truebit tags FILE`: the kind of tag, every tag, and the cover
def read_all_tags(file_path):
    audio, family = open_tagged_file(file_path)
    cover = read_cover(audio, family)
    cover_info = None
    if cover is not None:
        cover_info = {"mime": cover[1], "bytes": len(cover[0])}
    return {"family": FAMILY_NAMES[family], "tags": tag_rows(audio, family), "cover": cover_info}


# Saves the cover art as a picture file. Returns the path, or None if there is no cover.
def save_cover(file_path, picture_path):
    audio, family = open_tagged_file(file_path)
    cover = read_cover(audio, family)
    if cover is None:
        return None
    picture_path = Path(picture_path)
    if picture_path.suffix == "":
        picture_path = picture_path.with_suffix(".png" if cover[1] == "image/png" else ".jpg")
    picture_path.write_bytes(cover[0])
    return picture_path


# ---- Changing ----------------------------------------------------------------------------

# "3" -> (3, 0) and "3/12" -> (3, 12), for track and disc numbers in M4A files
def number_and_total(text):
    parts = text.split("/")
    try:
        number = int(parts[0])
        total = int(parts[1]) if len(parts) > 1 and parts[1] != "" else 0
    except ValueError:
        raise TagError(f'"{text}" isn\'t a number like 3 or 3/12.')
    return (number, total)


# Sets one tag (name is a common name like "title", or any other name)
def set_tag(audio, family, name, value):
    tags = audio.tags
    if family == "id3":
        if name == "comment":
            tags.delall("COMM")
            tags.add(COMM(encoding=3, lang="eng", desc="", text=[value]))
        elif name in ID3_FRAMES:
            frame_id = ID3_FRAMES[name]
            tags.delall(frame_id)
            tags.add(Frames[frame_id](encoding=3, text=[value]))
        else:  # any other name goes in a "user text" frame
            tags.delall("TXXX:" + name)
            tags.add(TXXX(encoding=3, desc=name, text=[value]))
    elif family == "vorbis":
        tags[VORBIS_KEYS.get(name, name)] = [value]
    elif family == "mp4":
        if name == "track" or name == "disc":
            tags[MP4_KEYS[name]] = [number_and_total(value)]
        elif name in MP4_KEYS:
            tags[MP4_KEYS[name]] = [value]
        else:
            tags[MP4_FREEFORM + name] = [MP4FreeForm(value.encode("utf-8"))]
    elif family == "asf":
        tags[ASF_KEYS.get(name, name)] = [value]
    elif family == "ape":
        tags[APE_KEYS.get(name, name)] = value


# Removes one tag (it's fine if it isn't there)
def remove_tag(audio, family, name):
    tags = audio.tags
    if family == "id3":
        if name == "comment":
            tags.delall("COMM")
        elif name in ID3_FRAMES:
            tags.delall(ID3_FRAMES[name])
        else:
            tags.delall("TXXX:" + name)
        return

    tables = {"vorbis": VORBIS_KEYS, "mp4": MP4_KEYS, "asf": ASF_KEYS, "ape": APE_KEYS}
    key = tables[family].get(name, name)
    if family == "mp4" and name not in MP4_KEYS:
        key = MP4_FREEFORM + name
    # Tag names don't always match in upper/lower case, so look for the key both ways
    for existing_key in list(tags.keys()):
        if existing_key.lower() == key.lower():
            del tags[existing_key]


# Puts in a new cover picture (JPG or PNG), replacing the old one
def set_cover(audio, family, picture_path):
    picture_path = Path(picture_path)
    extension = picture_path.suffix.lower()
    if extension in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    elif extension == ".png":
        mime = "image/png"
    else:
        raise TagError("The cover must be a .jpg or .png picture.")
    data = picture_path.read_bytes()

    if family == "id3":
        audio.tags.delall("APIC")
        audio.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
    elif family == "vorbis" and isinstance(audio, FLAC):
        audio.clear_pictures()
        audio.add_picture(make_picture(data, mime))
    elif family == "vorbis":  # OGG and Opus keep the picture as text inside a comment
        picture_text = base64.b64encode(make_picture(data, mime).write()).decode("ascii")
        audio.tags[OGG_PICTURE_KEY] = [picture_text]
    elif family == "mp4":
        image_format = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
        audio.tags["covr"] = [MP4Cover(data, imageformat=image_format)]
    else:
        raise TagError("TrueBit can't change cover art in WMA or APE files yet.")


# Takes the cover picture out
def remove_cover(audio, family):
    if family == "id3":
        audio.tags.delall("APIC")
    elif family == "vorbis" and isinstance(audio, FLAC):
        audio.clear_pictures()
    else:
        for key in list(audio.tags.keys()):
            if key.lower() in ("covr", OGG_PICTURE_KEY, "wm/picture") or key.lower().startswith("cover art"):
                del audio.tags[key]


# Changes a file's tags and saves them. By default this changes the file itself, for good.
# output_path = make a copy and change that instead. Returns the path that was changed.
def change_tags(file_path, set_values=None, remove_names=None, clear_all=False, cover_path=None,
                take_out_cover=False, output_path=None):
    # Step 1: work on a copy if one was asked for
    target_path = Path(file_path)
    if output_path is not None:
        shutil.copyfile(file_path, output_path)
        target_path = Path(output_path)

    audio, family = open_tagged_file(target_path)
    if audio.tags is None:
        audio.add_tags()

    # Step 2: clear everything, then remove and set single tags
    if clear_all:
        audio.tags.clear()
        if isinstance(audio, FLAC):
            audio.clear_pictures()
    for name in remove_names or []:
        remove_tag(audio, family, common_name(name))
    for name, value in (set_values or {}).items():
        set_tag(audio, family, common_name(name), value)

    # Step 3: the cover picture
    if take_out_cover:
        remove_cover(audio, family)
    if cover_path is not None:
        set_cover(audio, family, cover_path)

    # Step 4: save. MP3, WAV and AIFF get ID3 version 2.3, which Windows reads best.
    try:
        if family == "id3":
            audio.save(v2_version=3)
        else:
            audio.save()
    except PermissionError:
        raise TagError("Can't save: the file is read-only or open in another program (close your music player).")
    return target_path
