# Development and validation

The project matches the local Python/Poetry/Streamlit shape used by trade-bot while remaining a completely
separate personal repository.

## Canonical checks

```bash
make demo             # regenerate deterministic synthetic fixtures
make check            # Ruff, Black, mypy, pytest, native firmware policy tests, lock check
make firmware-hardware
make dashboard
```

Dashboard verification requires more than importing the Python module: start Streamlit, confirm an HTTP 200
response, and inspect all ten pages for the normal, thermal anomaly, and ingress drill sessions. The
launcher scans from port 8501 and binds to the first available IPv4 localhost port; set
`JARRED_DRIVE_PORT_START` to begin elsewhere. See
`docs/validation_report.md` for the most recent captured evidence.

## Privacy and networking

The only network client is an explicit home-LAN logger sync to the address shown in Devices / Sync. There is
no cloud storage, telemetry service, or analytics SDK. Device tokens are user-supplied at runtime and are not
stored by the app. Raw/processed sessions and annotations are ignored by Git. Synthetic fixtures are safe to
commit.

## Repository identity

This checkout must use the personal SSH alias and identity:

```text
remote: git@github-personal:Jbultema/jarred_drive.git
name:   Jbultema
email:  Jbultema@users.noreply.github.com
```

Do not inherit a work identity and do not add work-library dependencies.

## Native iPhone prototype

The app in `ios/JarredDrive.xcodeproj` requires the full Xcode application, not only Apple's Command Line
Tools. It targets iOS 17 and has no third-party packages, cloud account, analytics SDK, or VESC write path.

1. Install and launch Xcode once, then select it with
   `sudo xcode-select -s /Applications/Xcode.app/Contents/Developer` if needed.
2. Run `make demo-server`, open the project, and run **Jarred Drive** in an iPhone Simulator. The default
   `http://127.0.0.1:8765` address reaches the Mac-hosted synthetic logger.
3. For a physical phone, run
   `poetry run jarred-drive serve-demo --source data/demo --host 0.0.0.0 --port 8765`, put the phone and Mac on
   the same trusted Wi-Fi, and enter `http://<mac-lan-ip>:8765` in the app. Allow the local-network and Mac
   firewall prompts. Select a personal Apple development team in Xcode before installing on the phone.

The orange synthetic label is intentional: these sessions are software fixtures. The app preserves a verified
raw copy under its Application Support directory. The simulator uses the Mac process only as a stand-in for
hardware; the real ESP will implement the identical REST contract.

`make ios-build` provides a signing-free compiler check. Running the app still requires at least one iOS
Simulator runtime under Xcode **Settings → Components**, or a connected iPhone with a selected development
team.
