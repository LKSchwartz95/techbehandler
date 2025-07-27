## Features

- Launch a PySide6 desktop application for analysis
- Run a Flask based dashboard to review run results
- Optional Guard Mode for automatically watching a folder
- Live capture of network traffic using tshark
- Manage optional tools via the built in tool manager
- Configurable prompt templates for LLM based analysis
- System resource monitoring with psutil
- Repeated metrics collection via `collect_metrics_periodically`
- Optional security scans using lynis or osquery
- Nmap network scanning integration
- Aggregated system log collection
- Automated remediation suggestions based on LLM tags

## Requirements

Python 3.11+ and the dependencies listed in `requirements.txt` are required. You can install them with

```bash
pip install -r requirements.txt
```

Some features rely on third party utilities that can be installed through the Tool Manager dialog. Wireshark provides live packet capture, Eclipse MAT enables heap dump analysis and `nmap` powers the network scanner.

On Windows you can launch the application with `run_dumpbehandler.bat`. The
script will create a `venv` folder if needed, install dependencies and then run
`main.py`.

## Usage

Run the GUI directly:

```bash
python main.py
```

or start the dashboard manually:

```bash
python main.py dashboard
```

Then browse to [http://localhost:5000/](http://localhost:5000/) to view the web dashboard.
To protect the dashboard with a login prompt, set the environment variables `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` before starting the app. A `DASHBOARD_SECRET_KEY` can also be supplied to override the default session secret.

The application stores output under the `Resultat` directory.

### Guard Mode

Guard Mode continuously monitors a chosen folder and automatically processes any new `.hprof`, `.pcap`, `.pcapng` or `.txt` files that appear. Enable it from the **Dashboard & Guard Mode** tab in the GUI by selecting a folder and setting the scan interval. When a stable file is detected it is queued for analysis and the results become available in the dashboard.

The HTML templates backing the dashboard UI can be found under the [`templates`](templates/) directory, for example [index.html](templates/index.html) lists all recorded analysis runs.

## Packaging

You can create a portable ZIP archive of the application using the provided
`package.py` helper script:

```bash
python package.py
```

The script bundles all essential files while excluding caches and large
artifacts, outputting a timestamped zip file in the project root.


## Tests

Run the automated tests with [pytest](https://docs.pytest.org/):

```bash
pytest
```
