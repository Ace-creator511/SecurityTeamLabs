# SecurityTeamLabs

A Python command-line lab that reviews sign-in activity using synthetic data.
It flags events with five or more failed attempts, groups alerts by system and
sign-in type, and reports what the evidence establishes and what remains unknown.

## Run the demo

From the project folder, run:

```bash
python3 watcher_lab.py expected_sign_in.json practice_events.json
```

The demo processes five events and flags four for review. Two web sign-in alerts
for `practice-server` are grouped together. The sample records an expected
successful web sign-in for that server. The outcomes for its SSH alerts and
the laptop's web alerts remain unknown.

The script writes a dated report to `reports/`.
