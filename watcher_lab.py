import json
import sys
from datetime import datetime
from pathlib import Path
REVIEW_THRESHOLD = 5
def review_event(event):
    server = event["server"]
    attempts = event["failed_attempts"]
    needs_review = attempts >= REVIEW_THRESHOLD

    if needs_review:
        message = f"{server}: {attempts} failed sign-in attempts. Send for review."
    else:
        message = f"{server}: {attempts} failed sign-in attempts. Below the practice review threshold."

    return {
        "needs_review": needs_review,
        "message": message,
    }


first_argument = sys.argv[1] if len(sys.argv) > 1 else "expected_sign_in.json"
if first_argument.strip().casefold() == "open reports":
    import subprocess

    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    subprocess.run(["/usr/bin/open", str(reports_dir)], check=True)
    raise SystemExit(0)

def initial_review_status(evidence):
    prefix = "Your decision for this batch: "
    statuses = {
        "Pending": "Pending",
        "Investigate further": "Investigate further",
        "Close this review": "Closed",
    }
    for line in reversed(evidence.splitlines()):
        if line.startswith(prefix):
            return statuses.get(line[len(prefix):])
    return None


def current_review_status(original, initial_status):
    decisions = {
        "Follow-up decision: Investigate further": "Investigate further",
        "Follow-up decision: Close this review": "Closed",
    }
    for follow_up in sorted(original.parent.glob("review_follow_up_*.txt"), reverse=True):
        lines = follow_up.read_text(encoding="utf-8").splitlines()
        if len(lines) >= 2 and lines[0] == f"Original report: {original.name}":
            status = decisions.get(lines[1])
            if status:
                return status, follow_up
    return initial_status, None


command = first_argument.strip().casefold()
if command in ("show open reviews", "resume an open review"):
    reports_dir = Path(__file__).resolve().parent / "reports"
    open_reviews = []
    for original in sorted(reports_dir.glob("*.txt"), reverse=True):
        if original.name.startswith(("review_follow_up_", "review_evidence_")):
            continue
        initial_status = initial_review_status(original.read_text(encoding="utf-8"))
        if initial_status is None:
            continue
        status, _ = current_review_status(original, initial_status)
        if status in ("Pending", "Investigate further"):
            open_reviews.append((original, status))

    if command == "show open reviews":
        for original, status in open_reviews:
            print(f"{status} | {original.name}")
        print(f"Open reviews: {len(open_reviews)}")
        raise SystemExit(0)

    if not open_reviews:
        print("Open reviews: 0")
        raise SystemExit(0)

    selected = open_reviews[0][0]
    if len(open_reviews) > 1:
        choices = {}
        for number, (original, status) in enumerate(open_reviews, start=1):
            print(f"{number}. {status} | {original.name}")
            choices[str(number)] = original
        while True:
            choice = input("Choose a review number, or press Return to cancel: ").strip()
            if not choice:
                raise SystemExit(0)
            if choice in choices:
                selected = choices[choice]
                break
            print("Choose a number from the list.")

    print(f"Opening review: {selected.name}")
    first_argument = "Resume a review"
    sys.argv[2:] = [selected.name]

if first_argument.strip().casefold() == "resume a review":
    import subprocess

    reports_dir = (Path(__file__).parent / "reports").resolve()
    report_arguments = sys.argv[2:]
    if len(report_arguments) > 1:
        raise SystemExit("Provide one report filename or path.")
    if report_arguments:
        original = (reports_dir / Path(report_arguments[0]).expanduser()).resolve()
    else:
        picker = subprocess.run(
            [
                "/usr/bin/osascript",
                "-e", "on run argv",
                "-e", "set reportsFolder to (POSIX file (item 1 of argv)) as alias",
                "-e", 'return POSIX path of (choose file with prompt "Choose a pending review report" default location reportsFolder)',
                "-e", "end run",
                str(reports_dir),
            ],
            capture_output=True,
            text=True,
        )
        if picker.returncode != 0:
            if "(-128)" in picker.stderr:
                raise SystemExit("Review canceled.")
            raise SystemExit(f"Could not open the file picker: {picker.stderr.strip()}")

        original = Path(picker.stdout.rstrip("\n")).resolve()
    if original.parent != reports_dir or original.suffix.lower() != ".txt":
        raise SystemExit("Choose a text report from Watcher's reports folder.")

    evidence = original.read_text(encoding="utf-8").rstrip()
    initial_status = initial_review_status(evidence)
    if initial_status is None:
        raise SystemExit("Choose a batch report with a recorded decision.")

    status, latest_follow_up = current_review_status(original, initial_status)

    print(evidence)
    print()
    print(f"Current status: {status}")
    if latest_follow_up:
        print(f"Latest follow-up: {latest_follow_up.name}")

    original_line = f"Original report: {original.name}"
    print("\nReview history")
    original_lines = evidence.splitlines()
    for index in range(len(original_lines) - 1, -1, -1):
        line = original_lines[index]
        if line.startswith("Your decision for this batch: "):
            print(f"Original decision: {line.split(': ', 1)[1]}")
            next_line = index + 1
            if next_line < len(original_lines) and original_lines[next_line].startswith("Reason: "):
                print(original_lines[next_line])
            break

    history_files = [
        *reports_dir.glob("review_follow_up_*.txt"),
        *reports_dir.glob("review_evidence_*.txt"),
    ]
    for history_path in sorted(history_files, key=lambda entry: entry.stem.rsplit("_", 3)[-3:]):
        history_lines = history_path.read_text(encoding="utf-8").splitlines()
        if len(history_lines) < 2 or history_lines[0] != original_line:
            continue

        print()
        if history_path.name.startswith("review_follow_up_"):
            _, date, time, _ = history_path.stem.rsplit("_", 3)
            print(f"Follow-up recorded {date} {time.replace('-', ':')}")
        print("\n".join(history_lines[1:]))

    if status == "Closed":
        raise SystemExit(0)
    print("\n1. Investigate further")
    print("2. Close this review")
    print("3. Add an evidence note")
    choice = input("Enter 1, 2, or 3, or press Return to keep the current status: ").strip()
    while choice not in ("", "1", "2", "3"):
        choice = input("Please enter 1, 2, or 3, or press Return: ").strip()

    if choice == "3":
        note = input("Evidence note (Return to cancel): ").strip()
        if not note:
            raise SystemExit("No evidence note added.")

        now = datetime.now().astimezone()
        timestamp = now.strftime("%Y-%m-%d_%H-%M-%S_%f")
        note_path = reports_dir / f"review_evidence_{timestamp}.txt"
        with note_path.open("x", encoding="utf-8") as note_file:
            note_file.write(
                f"{original_line}\n"
                f"Evidence note added {now.isoformat(timespec='seconds')}\n"
                f"{note}\n"
            )
        print(f"Evidence note saved to {note_path}")
        print(f"Current status: {status}")
        raise SystemExit(0)

    if not choice:
        print(f"Review remains {status.lower()}.")
        raise SystemExit(0)

    decision = {"1": "Investigate further", "2": "Close this review"}[choice]
    reason = input("Reason (optional): ").strip()
    lines = [
        f"Original report: {original.name}",
        f"Follow-up decision: {decision}",
    ]
    if reason:
        lines.append(f"Reason: {reason}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    follow_up = reports_dir / f"review_follow_up_{timestamp}.txt"
    with follow_up.open("x", encoding="utf-8") as report_file:
        report_file.write("\n".join(lines) + "\n")

    print("\n" + "\n".join(lines))
    print(f"Follow-up saved to {follow_up}")
    raise SystemExit(0)

if first_argument.strip().casefold() == "review these sign-ins":
    import subprocess

    capture_arguments = sys.argv[2:]
    if capture_arguments:
        selected_paths = [Path(value).expanduser() for value in capture_arguments]
        for capture_path in selected_paths:
            if not capture_path.is_file():
                raise SystemExit(f"Capture file not found: {capture_path}")
    else:
        picker = subprocess.run(
            [
                "/usr/bin/osascript",
                "-e", 'set selectedFiles to choose file with prompt "Choose sign-in captures" with multiple selections allowed',
                "-e", 'set selectedPaths to {}',
                "-e", 'repeat with selectedFile in selectedFiles',
                "-e", 'set end of selectedPaths to POSIX path of (contents of selectedFile)',
                "-e", 'end repeat',
                "-e", 'set AppleScript\'s text item delimiters to linefeed',
                "-e", 'return selectedPaths as text',
            ],
            capture_output=True,
            text=True,
        )
        if picker.returncode != 0:
            if "(-128)" in picker.stderr:
                raise SystemExit("Review canceled.")
            raise SystemExit(f"Could not open the file picker: {picker.stderr.strip()}")

        selected_paths = [Path(line) for line in picker.stdout.splitlines()]
    if len(selected_paths) == 1 and selected_paths[0].suffix.lower() == ".xml":
        import base64
        import binascii
        import hashlib
        from email.parser import BytesHeaderParser
        from http.cookies import CookieError, SimpleCookie

        def session_value(raw_message, header_name):
            header_lines = raw_message.splitlines()[1:]
            if b"" in header_lines:
                header_lines = header_lines[:header_lines.index(b"")]
            headers = BytesHeaderParser().parsebytes(b"\n".join(header_lines))
            sessions = set()
            for value in headers.get_all(header_name, []):
                try:
                    cookies = SimpleCookie(value)
                except CookieError:
                    continue
                if "session" in cookies and cookies["session"].value:
                    sessions.add(cookies["session"].value)
            return headers, next(iter(sessions)) if len(sessions) == 1 else None

        import xml.etree.ElementTree as ET

        batch_path = selected_paths[0]
        try:
            export = ET.parse(batch_path).getroot()
        except (ET.ParseError, OSError):
            raise SystemExit(f"Could not read Burp XML: {batch_path.name}")

        records = []
        from datetime import datetime as CaptureDateTime

        def burp_capture_time(value):
            parts = (value or "").split()
            if len(parts) != 6:
                return None
            offsets = {"CST": "-0600", "CDT": "-0500", "UTC": "+0000", "GMT": "+0000"}
            offset = offsets.get(parts[4], parts[4])
            try:
                stamp = " ".join([*parts[:4], offset, parts[5]])
                return CaptureDateTime.strptime(
                    stamp, "%a %b %d %H:%M:%S %z %Y"
                ).timestamp()
            except ValueError:
                return None

        pending_logins = {}
        entries = []
        for entry_number, item in enumerate(export.findall("item"), start=1):
            capture_time = burp_capture_time(item.findtext("time"))
            # A login and its account request can share the same recorded second.
            account_request = (item.findtext("method") or "").strip().upper() == "GET"
            order = (
                capture_time if capture_time is not None else float("inf"),
                account_request,
                entry_number,
            )
            entries.append((order, item))

        for order, item in sorted(entries, key=lambda entry: entry[0]):
            entry_number = order[2]
            capture_time = None if order[0] == float("inf") else order[0]
            method = (item.findtext("method") or "").strip().upper()
            route = (item.findtext("path") or "").partition("?")[0]
            is_login = method == "POST" and route == "/login"
            status = (item.findtext("status") or "").strip()
            is_account = method == "GET" and route == "/my-account" and status == "200"
            if not (is_login or is_account):
                continue

            server = (item.findtext("host") or "").strip().lower()
            captured_at = (item.findtext("time") or "").strip()
            request_node = item.find("request")
            response_node = item.find("response")
            if is_account and (not server or request_node is None):
                continue
            if not server or not captured_at or request_node is None:
                raise SystemExit("A login entry is missing its host, capture time, or request.")

            messages = []
            for node in (request_node, response_node):
                payload = (node.text or "") if node is not None else ""
                if node is not None and node.get("base64", "").lower() == "true":
                    try:
                        messages.append(base64.b64decode("".join(payload.split()), validate=True))
                    except (binascii.Error, ValueError):
                        raise SystemExit("A login entry contains invalid Base64 data.")
                else:
                    messages.append(payload.encode("utf-8"))

            request, response = messages
            origin = (server, item.findtext("protocol"), item.findtext("port"))
            if is_account:
                if capture_time is None:
                    continue
                if not response.startswith((b"HTTP/2 200 ", b"HTTP/1.1 200 ")):
                    continue
                _, session = session_value(request, "Cookie")
                target = item.findtext("path")
                if session and target:
                    for login_record in pending_logins.pop((origin, target, session), []):
                        login_record["confirmed_account_entry"] = entry_number
                continue
            if not request:
                raise SystemExit("A login entry has an empty request.")

            attempt_hash = hashlib.sha256(
                captured_at.encode("utf-8") + b"\0" + request
            ).hexdigest()

            _, separator, body = response.partition(b"\r\n\r\n")
            if not separator:
                _, _, body = response.partition(b"\n\n")

            response_hash = hashlib.sha256(response).hexdigest()
            finding = "Outcome could not be determined from the saved response."
            if b"Invalid username or password." in body:
                finding = "Invalid username or password."

            records.append({
                "attempt_id": f"burp-{attempt_hash}",
                "entry_number": entry_number,
                "captured_at": captured_at,
                "capture_time": capture_time,
                "server": server,
                "alert_type": "web sign-in",
                "response": f"{finding} [response SHA-256: {response_hash}]",
            })

            if capture_time is not None and status == "302" and finding != "Invalid username or password.":
                headers, session = session_value(response, "Set-Cookie")
                target = headers.get("Location", "")
                if session and target.partition("?")[0] == "/my-account":
                    pending_logins.setdefault((origin, target, session), []).append(records[-1])

        if not records:
            raise SystemExit("No POST /login entries found in this Burp export.")
    elif len(selected_paths) == 1 and selected_paths[0].suffix.lower() == ".json":
        batch_path = selected_paths[0]
        with batch_path.open(encoding="utf-8") as batch_file:
            records = json.load(batch_file)
    else:
        if not selected_paths or any(path.suffix.lower() != ".txt" for path in selected_paths):
            raise SystemExit("Choose one Burp XML export, one batch JSON file, or one or more .txt captures.")

        batch_path = Path("sign_in_captures")
        records = []
        for capture_path in selected_paths:
            capture = capture_path.read_text(encoding="utf-8")
            header, separator, response = capture.partition("\n\n")
            fields = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
            required = ("Attempt-ID", "Server", "Alert-Type")
            if not separator or not all(fields.get(name, "").strip() for name in required):
                raise SystemExit(f"{capture_path.name} needs an Attempt-ID, Server, and Alert-Type.")
            records.append({
                "attempt_id": fields["Attempt-ID"].strip(),
                "server": fields["Server"].strip(),
                "alert_type": fields["Alert-Type"].strip(),
                "response": response,
            })

    attempts = {}
    attempt_sources = {}
    duplicates = []
    confirmed_accounts = {}
    login_times = {}
    for index, record in enumerate(records):
        if batch_path.suffix.lower() == ".xml":
            source_name = (
                f"{batch_path.name}, XML entry {record['entry_number']}, "
                f"captured {record['captured_at']}"
            )
        elif batch_path.suffix.lower() == ".json":
            source_name = batch_path.name
        else:
            source_name = selected_paths[index].name
        key = (record["server"], record["alert_type"], record["attempt_id"])
        if key in attempts:
            if attempts[key] != record["response"]:
                raise SystemExit(
                    f"Conflicting responses for {key[2]} on {key[0]}. "
                    "Check the batch before counting this attempt."
                )
            duplicates.append(
                f"{key[0]} | {key[1]} | {key[2]} from {source_name} "
                f"(first seen in {attempt_sources[key]})"
            )
        else:
            attempts[key] = record["response"]
            attempt_sources[key] = source_name
            if batch_path.suffix.lower() == ".xml":
                login_times[key] = record["capture_time"]

        if batch_path.suffix.lower() == ".xml" and "confirmed_account_entry" in record:
            confirmed_accounts.setdefault(
                key, (source_name, record["confirmed_account_entry"])
            )

    failures = {}
    successes = []
    unknown = []
    for (server, alert_type, attempt_id), response in attempts.items():
        if "Invalid username or password." in response:
            failures.setdefault((server, alert_type), []).append(attempt_id)
        elif (server, alert_type, attempt_id) in confirmed_accounts:
            source_name, account_entry = confirmed_accounts[(server, alert_type, attempt_id)]
            successes.append(
                f"Successful sign-in on {server}. Login from {source_name}. "
                f"Matching account-page response at XML entry {account_entry}."
            )
        else:
            unknown.append(
                f"{server} | {alert_type} | {attempt_id} "
                f"from {attempt_sources[(server, alert_type, attempt_id)]}: {response}"
            )

    review_cases = 0
    lines = [
        f"Reviewed files: {', '.join(path.name for path in selected_paths)}",
        f"Confirmed failed sign-ins: {sum(len(ids) for ids in failures.values())}",
        f"Duplicate records excluded: {len(duplicates)}",
        f"Unknown outcomes: {len(unknown)}",
    ]

    if batch_path.suffix.lower() == ".xml":
        lines.append(f"Confirmed successful sign-ins: {len(successes)}")
        lines.extend(successes)

    for (server, alert_type), attempt_ids in failures.items():
        result = review_event({"server": server, "failed_attempts": len(attempt_ids)})
        review_cases += int(result["needs_review"])
        if result["needs_review"] and batch_path.suffix.lower() == ".xml":
            failure_times = [
                login_times[(server, alert_type, attempt_id)]
                for attempt_id in attempt_ids
            ]
            latest_failure_time = (
                max(failure_times) if None not in failure_times else None
            )
            later_successes = [
                f"Later successful sign-in: {login_source}. "
                f"Matching account-page response at XML entry {account_entry}."
                for key, (login_source, account_entry) in confirmed_accounts.items()
                if key[:2] == (server, alert_type)
                and latest_failure_time is not None
                and login_times[key] is not None
                and login_times[key] > latest_failure_time
            ]
            if later_successes:
                follow_up = [
                    *later_successes,
                    "Still unknown: Whether the successful sign-in was related to the failures.",
                    "Next check: Verify who made the attempts and whether the successful sign-in was expected.",
                ]
            else:
                follow_up = [
                    "Still unknown: Whether a later sign-in succeeded.",
                    "Next check: In Burp HTTP history, look at the later login and account-page entries for this same host.",
                ]
            lines.extend([
                "",
                f"Review brief for {server}",
                f"{len(attempt_ids)} confirmed failed sign-ins reached the review threshold of {REVIEW_THRESHOLD} for this host.",
                *follow_up,
            ])

        evidence_sources = [
            f"{attempt_id} ({attempt_sources[(server, alert_type, attempt_id)]})"
            for attempt_id in attempt_ids
        ]
        lines.extend([
            "",
            f"{server} | {alert_type}",
            result["message"],
            f'Evidence: "Invalid username or password." in {", ".join(evidence_sources)}.',
        ])

    for duplicate in duplicates:
        lines.append(f"Duplicate excluded: {duplicate} already counted once.")
    for outcome in unknown:
        lines.append(f"Outcome unknown: {outcome}")

    if review_cases and batch_path.suffix.lower() == ".xml":
        # Use the unique attempts and their outcomes, independent of XML row order.
        evidence_rows = [
            [*key, attempts[key], key in confirmed_accounts]
            for key in sorted(attempts)
        ]
        encoded = json.dumps(evidence_rows, separators=(",", ":")).encode("utf-8")
        fingerprint = hashlib.sha256(encoded).hexdigest()
        fingerprint_line = f"Burp review fingerprint: {fingerprint}"
        reports_folder = Path(__file__).resolve().parent / "reports"

        candidates = sorted(
            reports_folder.glob("*.txt"),
            key=lambda report: report.name.rsplit("_", 3)[-3:],
            reverse=True,
        )
        for prior_report in candidates:
            evidence = prior_report.read_text(encoding="utf-8")
            if fingerprint_line not in evidence.splitlines():
                continue
            initial_status = initial_review_status(evidence)
            if initial_status is None:
                continue
            status, _ = current_review_status(prior_report, initial_status)
            print(f"Existing review: {prior_report.name}")
            print(f"Current status: {status}")
            choice = input("Press Return to use this report, or type new to create another: ")
            if choice.strip().casefold() != "new":
                import runpy

                script_path = str(Path(__file__).resolve())
                sys.argv = [script_path, "Resume a review", str(prior_report.resolve())]
                runpy.run_path(script_path, run_name="__main__")
                raise SystemExit(0)
            break

        lines.extend(["", fingerprint_line])

    lines.extend(["", f"Cases for your review: {review_cases}"])
    brief = "\n".join(lines)

    if review_cases:
        print(brief)
        print("\nYour decision for this batch:")
        print("1. Investigate further")
        print("2. Close this review")

        choice = input("Enter 1 or 2, or press Return to leave pending: ").strip()
        while choice not in ("", "1", "2"):
            choice = input("Please enter 1 or 2, or press Return: ").strip()

        decisions = {"": "Pending", "1": "Investigate further", "2": "Close this review"}
        decision = decisions[choice]
        reason = input("Reason (optional): ").strip() if choice else ""

        decision_lines = [f"Your decision for this batch: {decision}"]
        if reason:
            decision_lines.append(f"Reason: {reason}")
        decision_summary = "\n".join(decision_lines)
        brief += "\n\n" + decision_summary
        print("\n" + decision_summary)

    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    report_path = reports_dir / f"{batch_path.stem}_{timestamp}.txt"
    with report_path.open("x", encoding="utf-8") as report_file:
        report_file.write(brief + "\n")

    if not review_cases:
        print(brief)
    print(f"Report saved to {report_path}")
    raise SystemExit(0)
if first_argument.strip().casefold() == "review this login":
    import subprocess

    picker = subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            'POSIX path of (choose file with prompt "Choose a saved login response")',
        ],
        capture_output=True,
        text=True,
    )

    if picker.returncode != 0:
        if "(-128)" in picker.stderr:
            raise SystemExit("Review canceled.")
        raise SystemExit(f"Could not open the file picker: {picker.stderr.strip()}")

    first_argument = picker.stdout.rstrip("\n")
    if Path(first_argument).suffix.lower() != ".txt":
        raise SystemExit("Choose a saved login response ending in .txt.")

reviewing_response = Path(first_argument).suffix.lower() == ".txt"
if reviewing_response:
    events_name = first_argument
else:
    events_name = sys.argv[2] if len(sys.argv) > 2 else "practice_events.json"

events_path = Path(__file__).parent / events_name
if events_path.suffix.lower() == ".txt":
    response = events_path.read_text(encoding="utf-8")
    if "Invalid username or password." not in response:
        raise SystemExit("The saved response does not show a recognized login failure.")

    events = [
        {
            "server": "portswigger-csrf-lab",
            "alert_type": "web sign-in",
            "failed_attempts": 1,
        }
    ]
else:
    with events_path.open("r", encoding="utf-8") as events_file:
        events = json.load(events_file)

login_summary = ""

if events_path.suffix.lower() == ".txt":
    login_summary = (
        "One failed sign-in. No decision needed.\n"
        f"Reviewed file: {events_path.name}\n"
        'The saved response says "Invalid username or password."\n'
        f"One attempt is below the review threshold of {REVIEW_THRESHOLD}."
    )
    print(login_summary)
    print()
reports = []
review_queue = []

for current_event in events:
    result = review_event(current_event)
    report = result["message"]
    reports.append(report)
    print(report)

    if result["needs_review"]:
        review_queue.append(current_event)

print(f"Review complete. {len(reports)} events processed.")
print(f"Events waiting for review: {len(review_queue)}")

alert_groups = {}

for queued_event in review_queue:
    server = queued_event["server"]
    alert_type = queued_event["alert_type"]
    group_key = (server, alert_type)

    if group_key not in alert_groups:
        alert_groups[group_key] = []

    alert_groups[group_key].append(queued_event)

sorter_reports = []

for (server, alert_type), alerts in alert_groups.items():
    alert_count = len(alerts)

    if alert_count > 1:
        message = f"Sorter: Grouped {alert_count} {alert_type} alerts for {server}."
    else:
        message = f"Sorter: {server} has one {alert_type} alert."

    sorter_reports.append(message)
    print(message)
def investigate_case(case):
    counts = []

    for alert in case["alerts"]:
        counts.append(str(alert["failed_attempts"]))

    evidence = ", ".join(counts)
    sign_in = case["successful_sign_in"]

    if sign_in is None:
        outcome = (
            "Whether anyone signed in successfully is unknown. "
            "Next check: Look for successful sign-ins around the time of these alerts."
        )
    else:
        expected = sign_in.get("expected")

        if expected is True:
            access_note = "The practice record marks this access as expected."
        elif expected is False:
            access_note = "The practice record marks this access as unexpected."
        else:
            access_note = (
                "Whether this access was expected is unknown. "
                "Next check: Ask the account owner whether they expected this sign-in."
            )

        outcome = (
            f"The practice log shows a successful sign-in at {sign_in['time']} "
            f"using the account {sign_in['account']}. {access_note}"
        )

    return (
        f"Detective: {case['server']} | {case['alert_type']}. "
        f"Failed attempts reported in each alert: {evidence}. "
        f"{outcome}"
    )

successful_sign_ins = {}

if not reviewing_response:
    scenario_path = Path(__file__).parent / first_argument

    with scenario_path.open(encoding="utf-8") as scenario_file:
        sign_in_record = json.load(scenario_file)

    sign_in_key = (sign_in_record["server"], sign_in_record["alert_type"])
    successful_sign_ins = {sign_in_key: sign_in_record}
detective_reports = []
fixer_proposals = []
simulated_suspensions = set()
for (server, alert_type), alerts in alert_groups.items():
    case = {
        "server": server,
        "alert_type": alert_type,
        "alerts": alerts,
        "successful_sign_in": successful_sign_ins.get((server, alert_type)),
    }
    finding = investigate_case(case)
    detective_reports.append(finding)
    print(finding)

    sign_in = case["successful_sign_in"]

    if (
        alert_type == "web sign-in"
        and sign_in is not None
        and sign_in.get("expected") is False
    ):
        account = sign_in["account"]

        proposed_action = ("suspend web sign-in", server, account)

        brief = (
            "Decision brief (simulation)\n"
            f"Evidence: The practice log records a successful web sign-in "
            f"using {account} on {server} at {sign_in['time']}. "
            "The practice record marks it as unexpected.\n"
            "Still unknown: Who used the account and whether the successful "
            "sign-in was related to the failed attempts.\n"
            f"Proposed action: Temporarily suspend new web sign-ins "
            f"for {account} on {server}.\n"
            f"Impact of acting now: {account} would be unable to start a new "
            f"web session on {server} during the suspension.\n"
            "Impact of waiting: The account could still be used for new web sign-ins "
            "while you verify who used it.\n"
            f"Decision target: {account} on {server}, new web sign-ins only."
        )
        print(brief)

        choice = input("Type approve, decline, or press Return to leave pending: ")
        choice = choice.strip().lower()
        operator_decision = (choice, proposed_action)

        if operator_decision == ("approve", proposed_action):
            simulated_suspensions.add((server, account))
            status = "Simulated suspension applied."

            if (server, account) in simulated_suspensions:
                verification = f"Confirmed in the simulation for {account} on {server}."
            else:
                verification = f"No simulated suspension found for {account} on {server}."
        elif operator_decision == ("decline", proposed_action):
            status = "Declined by operator."
            verification = "Skipped because the proposal was declined."
        else:
            status = "Awaiting your approval."
            verification = "Pending approval."

        result = f"Status: {status}\nVerification: {verification}"
        fixer_proposals.append(f"{brief}\n{result}")
        print(result)

        

reports_dir = Path(__file__).parent / "reports"
reports_dir.mkdir(exist_ok=True)

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
report_path = reports_dir / f"{events_path.stem}_{timestamp}.txt"

with report_path.open("x", encoding="utf-8") as report_file:
    if login_summary:
        report_file.write(login_summary + "\n\n")
    for report in reports:
        report_file.write(report + "\n")

    report_file.write(f"Review complete. {len(reports)} events processed.\n")
    report_file.write(f"Events waiting for review: {len(review_queue)}\n")

    if sorter_reports:
        report_file.write("\nSorter summary\n")
        for message in sorter_reports:
            report_file.write(message + "\n")

    if detective_reports:
        report_file.write("\nDetective findings\n")
        for finding in detective_reports:
            report_file.write(finding + "\n")

    if fixer_proposals:
        report_file.write("\nFixer proposals\n")
        for proposal in fixer_proposals:
            report_file.write(proposal + "\n")

print(f"Report saved to {report_path}")
