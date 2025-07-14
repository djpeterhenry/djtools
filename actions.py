#!/usr/bin/env python3.11

from __future__ import print_function

import ableton_aid as aa
import export_rekordbox
import argh
import os
import sys
from collections import defaultdict
import difflib
import re
import pprint
import discogs_client
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import typing as T
import demucs as demucs_py


def add_bpms():
    """Add BPM values for new files in the database. Input required for each file."""
    db_dict = aa.read_db_file()
    alc_files = aa.get_ableton_files()
    for filename in alc_files:
        if filename in db_dict:
            continue

        print(filename)
        bpm = aa.get_int("BPM: ")
        if bpm is None:
            print("Stopping and saving...")
            break

        # record the result in the database
        new_record = {"bpm": bpm, "tags": []}
        db_dict[filename] = new_record
        print("Inserted: " + str(new_record))
    aa.write_db_file(db_dict)


def add_keys():
    """Add musical keys for files in the database by analyzing audio using keyfinder-cli."""
    db_dict = aa.read_db_file()

    valid_alc_files = aa.get_valid_alc_files(db_dict)
    aa.update_db_clips(valid_alc_files, db_dict)
    # Write the updated clips before considering any keys
    aa.write_db_file(db_dict)

    for filename in valid_alc_files:
        record = db_dict[filename]
        key = record.get("key")
        if not key or key[-1] == "?":
            print("Need key for: " + filename)

            sample_filepath = os.path.abspath(record["clip"]["sample"])
            assert os.path.isfile(sample_filepath)

            new_key = aa.get_key_from_keyfinder_cli(sample_filepath)
            print("new_key: " + new_key)
            if new_key is None:
                continue
            record["key"] = new_key
        else:
            pass
    # Write the database only once at the end.
    # If you ever need to batch process the whole library again (heaven forbid) then change this.
    aa.write_db_file(db_dict)


def edit_bpm(edit_filename):
    """Edit BPM value for a specific file."""
    assert os.path.isfile(edit_filename)
    print(edit_filename)
    db_dict = aa.read_db_file()
    bpm = None
    if edit_filename in db_dict:
        record = db_dict[edit_filename]
        bpm = record["bpm"]
    bpm = aa.get_int("BPM [%s]: " % bpm)
    if bpm is None:
        print("Aborting single edit")
        sys.exit(1)
    new_record = record
    new_record["bpm"] = bpm
    db_dict[edit_filename] = new_record
    print("Inserted: " + str(new_record))
    aa.write_db_file(db_dict)


def rename_tag(tag_old, tag_new):
    """Rename a tag throughout the database."""
    db_dict = aa.read_db_file()
    for _, record in sorted(db_dict.items()):
        tags = record["tags"]
        tags = [x if (x != tag_old) else tag_new for x in tags]
        record["tags"] = tags
    aa.write_db_file(db_dict)


def list_tags():
    """List all tags and their frequencies used in the database."""
    db_dict = aa.read_db_file()
    files = aa.get_rekordbox_files(db_dict)
    tag_to_count = defaultdict(int)
    for f in files:
        record = db_dict[f]
        tags = record["tags"]
        for tag in tags:
            tag_to_count[tag] += 1
    for tag, count in tag_to_count.items():
        print(tag, ":", count)


def list_missing():
    """List files that are in the database but no longer exist in the filesystem."""
    missing = aa.get_missing()
    for f in missing:
        print(f)


def transfer_missing():
    """Interactive tool to handle missing files by transferring their data to similar files or deleting them."""
    db_dict = aa.read_db_file()
    alc_file_set = set(aa.get_ableton_files())
    alc_file_list = list(alc_file_set)
    missing = aa.get_missing()
    for f in missing:
        record = db_dict[f]
        ts_list = aa.get_ts_list(record)
        ts_len = len(ts_list)
        print(f, "plays:", ts_len)

        close = difflib.get_close_matches(f, alc_file_list, cutoff=0.3, n=10)
        for index, other in enumerate(close):
            print(index, ":", other)

        choice = aa.get_int("Choice (-1 explicit delete):")
        if choice is not None:
            if choice == -1:
                del db_dict[f]
                aa.write_db_file(db_dict)
            else:
                try:
                    target = close[choice]
                except KeyError:
                    continue
                target_record = db_dict[target]
                target_ts_list = aa.get_ts_list(target_record)
                both_ts_list = sorted(list(set(target_ts_list + ts_list)))
                target_record["ts_list"] = both_ts_list
                print(
                    "ts_list:",
                    ts_list,
                    "target_ts_list:",
                    target_ts_list,
                    "both_ts_list:",
                    both_ts_list,
                )
                # Transfer tags
                for old_tag in record["tags"]:
                    if old_tag not in target_record["tags"]:
                        target_record["tags"].append(old_tag)

                # Transfer a bunch of metadata.
                # It would be nice to organize this better in the record.
                for field in [
                    "key",
                    "release_year_discogs",
                    "release_year_bandcamp",
                    "release_year_manual",
                    "labels_discogs",
                ]:
                    if field in record and field not in target_record:
                        target_record[field] = record[field]

                # Delete old record
                del db_dict[f]
                aa.write_db_file(db_dict)


def transfer_other(other_db_filename):
    """Transfer timestamp data from another database file into the current database."""
    db_dict = aa.read_db_file()
    other_db_dict = aa.read_db_file(other_db_filename)
    for filename, record in db_dict.items():
        if filename in other_db_dict:
            other_record = other_db_dict[filename]
            other_ts_list = aa.get_ts_list(other_record)
            ts_list = aa.get_ts_list(record)
            # See if we are adding any new timestamps for sanity
            num_new_ts = len(set(other_ts_list) - set(ts_list))
            if num_new_ts > 0:
                print(filename, "adding", num_new_ts, "new timestamps")
                both_ts_list = sorted(list(set(other_ts_list + ts_list)))
                record["ts_list"] = both_ts_list
    aa.write_db_file(db_dict)


def print_records():
    """Print all records in the database."""
    db_dict = aa.read_db_file()
    for filename, record in db_dict.items():
        print(filename + " " + str(record))


def print_record(alc_filename):
    """Print detailed information for a specific file."""
    db_dict = aa.read_db_file()
    record = db_dict[alc_filename]
    pprint.pprint(record)


def print_pretty(output_file):
    """Write database contents to a file in a readable format."""
    db_dict = aa.read_db_file()
    with open(output_file, "w") as f:
        for filename, record in sorted(db_dict.items()):
            print("---", file=f)
            pprint.pprint(filename, f)
            pprint.pprint(record, f)


def summarize_keys():
    """Print frequency of musical keys in the database."""
    db_dict = aa.read_db_file()
    alc_file_set = set(aa.get_ableton_files())
    key_frequency = {}
    for filename, record in sorted(db_dict.items()):
        if filename not in alc_file_set:
            continue
        key = record.get("key")
        cam_key = aa.get_camelot_key(key)
        if cam_key is None:
            continue
        key_key = aa.reverse_camelot_dict[cam_key]
        if key_key not in key_frequency:
            key_frequency[key_key] = 0
        key_frequency[key_key] = key_frequency[key_key] + 1
    # sort by count
    by_count = []
    for key, count in sorted(key_frequency.items()):
        by_count.append((count, key))
    by_count.sort()
    by_count.reverse()
    for count, key in by_count:
        print("%4s - %3s: %d" % (key, aa.get_camelot_key(key), count))


def print_xml(alc_filename):
    """Print the XML content of an Ableton Live clip file."""
    assert os.path.isfile(alc_filename)
    print(aa.alc_to_str(alc_filename))


def print_audioclip(alc_filename):
    """Print audio clip information from an Ableton Live clip file."""
    assert os.path.isfile(alc_filename)
    pprint.pprint(aa.get_audioclip_from_alc(alc_filename))


def print_audioclips(als_filename):
    """Print all audio clip information from an Ableton Live set file."""
    assert os.path.isfile(als_filename)
    pprint.pprint(aa.get_audioclips_from_als(als_filename))


def rekordbox_xml(rekordbox_filename):
    """Export database to Rekordbox XML format."""
    export_rekordbox.export_rekordbox_xml(rekordbox_filename=rekordbox_filename)


def test_lists():
    """Test reading track lists from the lists folder."""
    db_dict = aa.read_db_file()
    name_to_file = aa.get_list_name_to_file(aa.LISTS_FOLDER)
    for name, list_file in sorted(name_to_file.items()):
        print("---", name)
        for display, f in aa.get_list_from_file(list_file, db_dict):
            if f is None:
                print(display)


def cue_to_tracklist(cue_filename, tracklist_filename):
    """Convert a cue sheet to a tracklist format."""

    class Track(object):
        def __init__(self):
            self.artist = None
            self.song = None
            self.index = None

        def __str__(self):
            return "[{}] {} - {}".format(self.index, self.artist, self.song)

    tracks = []
    track = Track()
    # assume [key] on all tracks?
    p_title = re.compile(r'\tTITLE "(.*) \[')
    p_performer = re.compile(r'\tPERFORMER "(.*)"')
    p_index = re.compile(r"\tINDEX 01 (.*)")
    with open(cue_filename) as f:
        for line in f.readlines():
            m_title = p_title.search(line)
            m_performer = p_performer.search(line)
            m_index = p_index.search(line)
            if m_title:
                track.song = m_title.group(1).strip()
            elif m_performer:
                track.artist = m_performer.group(1).strip()
            elif m_index:
                track.index = m_index.group(1).strip()
                tracks.append(track)
                track = Track()
    # for t in tracks:
    #     print (t)
    with open(tracklist_filename, "w") as w:
        for t in tracks:
            w.write("{}\n".format(str(t)))


def generate_lists(output_path):
    """Generate various sorted track lists and save them to files."""
    aa.generate_lists(output_path)


def _simplify_track(track):
    """Remove common suffixes like (Original Mix), (Radio Edit), (Acapella), (feat. Artist) from track name."""
    pattern = r"\s*\((Original|Radio|Acapella|feat[^)]*)[^)]*\)"
    if not re.search(pattern, track, re.IGNORECASE):
        return None
    simplified = re.sub(pattern, "", track, flags=re.IGNORECASE)
    # Keep removing parentheses blocks until no more matches
    while re.search(pattern, simplified, re.IGNORECASE):
        simplified = re.sub(pattern, "", simplified, flags=re.IGNORECASE)
    simplified = simplified.strip()
    print(f"Trying simplified track name: {simplified}")
    return simplified


def _process_track_metadata(db_dict, filename, record, source_name, retry=False):
    """Common helper for processing track metadata from different sources.

    Args:
        db_dict: Database dictionary
        filename: Name of file to process
        record: Record from database
        source_name: Source name (e.g. "discogs", "bandcamp")
        retry: If True, process even if source already has data (unless it has a valid year)
    """
    year_key = f"release_year_{source_name}"
    # Skip if we already have info and not in retry mode, or if we have a valid year in retry mode
    if year_key in record:
        if not retry or record[year_key] is not None:
            return None, None

    artist, track = aa.get_artist_and_track(filename)
    if not artist or not track:
        print(f"Skipping {filename}: Unable to parse artist and track.")
        record[year_key] = None
        aa.write_db_file(db_dict)
        return None, None

    print(f"Searching for: {artist} - {track}")
    return artist, track


def release_dates_discogs(n: int = None, retry: bool = False):
    """Search for release dates on Discogs for songs ordered by play count.

    Args:
        n: Number of songs to process (None for all)
        retry: If True, only process songs with None for release_year_discogs
    """
    db_dict = aa.read_db_file()
    d = discogs_client.Client("DJTools/1.0", user_token=aa.DISCOGS_API_KEY)

    # Get list of files to process, sorted by play count
    process_files = []
    for filename, record in db_dict.items():
        if retry and record.get("release_year_discogs") is not None:
            continue
        ts_count = len(aa.get_ts_list_date_limited(record))
        if ts_count > 0:  # Only include songs that have been played
            process_files.append((ts_count, filename))

    # Sort by play count (descending)
    process_files.sort(reverse=True)
    if n is not None:
        process_files = process_files[:n]

    print(f"Processing {len(process_files)} songs{' (retry mode)' if retry else ''}")

    for plays, filename in process_files:
        record = db_dict[filename]
        print(f"\n{plays} plays: {filename}")

        artist, track = _process_track_metadata(
            db_dict, filename, record, "discogs", retry=retry
        )
        if not artist:  # Skip if we couldn't process metadata
            continue

        try:
            results = d.search(track, artist=artist, type="release")

            # If no results, try with simplified track name
            if not results:
                simplified = _simplify_track(track)
                if simplified:
                    results = d.search(simplified, artist=artist, type="release")

            if results:
                release = results[0]
                labels = [label.name for label in release.labels]

                record["release_year_discogs"] = release.year
                if labels:  # Only store labels if we found some
                    record["labels_discogs"] = labels

                if release.year:
                    print(f"Found release date for {filename}: {release.year}")
                    print(f"Label(s): {', '.join(labels) if labels else 'Unknown'}")
                    aa.write_db_file(db_dict)
                else:
                    print(f"No release date found for {filename}.")
                    print(f"Label(s): {', '.join(labels) if labels else 'Unknown'}")
                    record["release_year_discogs"] = None
                    aa.write_db_file(db_dict)
            else:
                print(f"No results found for {filename}.")
                record["release_year_discogs"] = None
                aa.write_db_file(db_dict)

        except Exception as e:
            print(f"Error searching for {filename}: {e}")


def _get_missing_release_dates(db_dict, order_by_date=False):
    # Get a list of files with no release year or 0 release year.
    files_list = [f for f, record in db_dict.items() if not aa.get_release_year(record)]
    # Only care about rekordbox files
    files_list = aa.filter_recordbox_files(files_list, db_dict)

    if order_by_date:
        return aa.generate_date_plus_alc(files_list, db_dict)
    else:
        # Sort by play count
        count_tuples = [
            (len(aa.get_ts_list_date_limited(db_dict[f])), f) for f in files_list
        ]
        count_tuples.sort(reverse=True)
        return [f for _, f in count_tuples]


def release_dates_bandcamp(n: int, order_by_date: bool = False):
    """Search for release dates on Bandcamp for songs missing dates.

    Args:
        n: Number of songs to process
        order_by_date: If True, order by last played/added date instead of play count
    """
    db_dict = aa.read_db_file()
    missing_files = _get_missing_release_dates(db_dict, order_by_date)[:n]

    if not missing_files:
        print("No files found missing release years")
        return

    print(f"Searching Bandcamp for top {n} songs missing dates:")
    print("-" * 70)

    for filename in missing_files:
        record = db_dict[filename]

        artist, track = _process_track_metadata(db_dict, filename, record, "bandcamp")
        if not artist:  # Skip if we couldn't process metadata
            continue

        try:
            # Try with original track name first
            url = _get_bandcamp_url(artist, track)
            print(f"Searching URL: {url}")
            response = requests.get(url)
            soup = BeautifulSoup(response.text, "html.parser")

            # Look for any search results using broader selectors
            results = soup.select("li.searchresult")
            if not results:
                results = soup.select(
                    ".result-items li"
                )  # Another common Bandcamp selector

            print(f"Found {len(results)} results")

            if not results:
                simplified = _simplify_track(track)
                if simplified:
                    url = _get_bandcamp_url(artist, simplified)
                    print(f"Trying simplified URL: {url}")
                    response = requests.get(url)
                    soup = BeautifulSoup(response.text, "html.parser")
                    results = soup.select("li.searchresult") or soup.select(
                        ".result-items li"
                    )
                    print(f"Found {len(results)} results with simplified search")

            if results:
                result = results[0]
                print("First result HTML:")
                print(result.prettify()[:500])  # Print first 500 chars of the HTML

                # Try multiple selectors for date
                date_selectors = [
                    ".released",
                    ".release-date",
                    'div[class*="release"]',  # Any class containing "release"
                    ".subhead",  # Sometimes contains the date
                ]

                for selector in date_selectors:
                    date_el = result.select_one(selector)
                    if date_el:
                        date_text = date_el.text.strip()
                        print(f"Found date text with selector {selector}: {date_text}")
                        try:
                            # Look for a year in the text
                            year_match = re.search(r"\b20\d{2}\b", date_text)
                            if year_match:
                                year = int(year_match.group(0))
                                record["release_year_bandcamp"] = year
                                print(f"Found release year: {year}")
                                aa.write_db_file(db_dict)
                                break
                        except (ValueError, IndexError) as e:
                            print(f"Failed to parse date text: {date_text}")
                            print(f"Error: {e}")
                else:
                    print("No valid release date found in any selector")
            else:
                print("No results found in HTML")

            if "release_year_bandcamp" not in record:
                record["release_year_bandcamp"] = None
                aa.write_db_file(db_dict)

        except Exception as e:
            print(f"Error searching: {e}")
            import traceback

            traceback.print_exc()


def _get_bandcamp_url(artist, track):
    """Helper to construct Bandcamp search URL."""
    search_term = quote_plus(f"{artist} {track}")
    return f"https://bandcamp.com/search?q={search_term}&item_type=t"


def clear_release_date_none_values():
    """Remove any None values for release date fields in the database."""
    db_dict = aa.read_db_file()
    date_fields = ["release_year_discogs"]

    modified = False
    for _, record in db_dict.items():
        for field in date_fields:
            if field in record and record[field] is None:
                del record[field]
                modified = True

    if modified:
        aa.write_db_file(db_dict)
        print("Removed None values from release date fields")
    else:
        print("No None values found in release date fields")


def summarize_years():
    """Print summary statistics about Discogs release years in the database."""
    db_dict = aa.read_db_file()

    rekrodbox_files = aa.get_rekordbox_files(db_dict)
    total_files = len(rekrodbox_files)
    files_with_year = 0
    year_counts = defaultdict(int)

    for filename in rekrodbox_files:
        record = db_dict[filename]
        year = aa.get_release_year(record)
        if year is not None:
            files_with_year += 1
            year_counts[year] += 1

    files_without_year = total_files - files_with_year

    print(f"Total Rekordbox files: {total_files}")
    print(f"Files with release year: {files_with_year}")
    print(f"Files without release year: {files_without_year}")
    print("\nRelease year distribution:")

    for year in sorted(year_counts.keys()):
        count = year_counts[year]
        print(f"{year}: {count}")


def release_dates_manual(
    order_by_date: bool = True, search_terms: T.Optional[T.List[str]] = None
):
    """Manually enter release dates for files that don't have one.

    Args:
        order_by_date: If True, order by last played/added date instead of play count
    """
    print("search_terms:", search_terms)

    db_dict = aa.read_db_file()
    if search_terms:
        # Filter files based on search terms
        files_to_edit = [
            f
            for f in db_dict
            if all(term.lower() in f.lower() for term in search_terms)
        ]
    else:
        files_to_edit = _get_missing_release_dates(db_dict, order_by_date)

    for filename in files_to_edit:
        record = db_dict[filename]

        last_ts = aa.get_alc_or_last_ts(record)
        last_ts_date = aa.get_date_from_ts(last_ts)
        add_ts = aa.get_alc_ts(record)
        add_ts_date = aa.get_date_from_ts(add_ts)

        # If you used search_terms there may be an existing release year
        existing_year = aa.get_release_year(record)
        existing_year_str = f" ({existing_year})" if existing_year is not None else ""

        print(f"\n{last_ts_date} ({add_ts_date}){existing_year_str}: {filename}")

        query = f"{os.path.splitext(filename)[0]} release date"
        # Form a clickable google query for this
        # Make the query clickable
        print(f"Google query: https://www.google.com/search?q={quote_plus(query)}")

        year = aa.get_int("Enter release year (or leave blank to skip): ")
        if year is not None:
            record["release_year_manual"] = year
            print(f"Added release year: {year}")
            aa.write_db_file(db_dict)
        else:
            print("Skipping this file.")


def remove_recent_timestamps(minutes: int):
    """Remove timestamps from the database that are within the last 'minutes' minutes."""
    db_dict = aa.read_db_file()
    past_ts = aa.get_past_ts(minutes * 60)

    num_removed = 0

    for filename, record in db_dict.items():
        ts_list = record.get("ts_list", [])
        # Filter out timestamps that are more recent than the cutoff
        filtered_ts_list = [ts for ts in ts_list if ts < past_ts]
        num_removed += len(ts_list) - len(filtered_ts_list)
        record["ts_list"] = filtered_ts_list

    aa.write_db_file(db_dict)
    print(
        f"Removed {num_removed} timestamps within the last {minutes} minutes from the database."
    )


def demucs(input_filename):
    """
    Run demucs on the sample for the specifiec ableton file.

    Produce a corresponding ableton file for the vocal track.
    """
    db_dict = aa.read_db_file()
    record = db_dict.get(input_filename)
    if not record:
        print(f"File {input_filename} not found in the database.")
        return

    # Use the original sample from the ableton file.
    # You could also use the existing rekordbox sample which might be easier for demucs to handle.
    sample_filepath = os.path.abspath(record["clip"]["sample"])
    if not os.path.isfile(sample_filepath):
        print(f"Sample file {sample_filepath} does not exist.")
        return

    output_base_folder = "/tmp/demucs_output"
    model_name = "htdemucs"
    # Supposedly slightly better at 4x computational cost:
    # model_name = "htdemucs_ft"

    demucs_result = demucs_py.demucs(
        sample_filepath, output_base_folder, model_name=model_name
    )
    if not demucs_result:
        print(f"Demucs processing failed for {sample_filepath}.")
        return

    expected_output_folder = os.path.join(
        output_base_folder,
        f"{model_name}",
        f"{os.path.splitext(os.path.basename(sample_filepath))[0]}",
    )
    output_vocal_filepath = os.path.join(expected_output_folder, "vocals.wav")
    if not os.path.isfile(output_vocal_filepath):
        print(f"Expected output file {output_vocal_filepath} does not exist.")
        return

    print(
        f"Demucs processing completed for {sample_filepath}. Vocal track saved to {output_vocal_filepath}."
    )

    # Now referencing get_xml_clip_info to replace in ableton file we would need to support both old and new format.
    # Some ideas:
    # - only support the new format, check before we run this that it is the new format, force resave otherwise.


if __name__ == "__main__":
    parser = argh.ArghParser()
    parser.add_commands(
        [
            add_bpms,
            add_keys,
            edit_bpm,
            rename_tag,
            list_tags,
            list_missing,
            transfer_missing,
            transfer_other,
            print_records,
            print_record,
            print_pretty,
            print_xml,
            print_audioclip,
            print_audioclips,
            rekordbox_xml,
            test_lists,
            cue_to_tracklist,
            generate_lists,
            release_dates_discogs,
            release_dates_bandcamp,
            clear_release_date_none_values,
            summarize_years,
            summarize_keys,
            release_dates_manual,
            remove_recent_timestamps,
            demucs,
        ]
    )
    parser.dispatch()
