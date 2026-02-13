import time
import pandas as pd
from datetime import datetime, timezone
from entsoe import EntsoePandasClient

TZ = "Europe/Amsterdam"

def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

def _expected_hours(start: pd.Timestamp, end: pd.Timestamp) -> int:
    # DST-proof: 23/24/25 afhankelijk van zomertijdwissel
    return len(pd.date_range(start, end, freq="h", inclusive="left", tz=TZ))

def _fetch(client: EntsoePandasClient, eic: str, start: pd.Timestamp, end: pd.Timestamp):
    """
    Haalt day-ahead prijzen op en geeft een tz-aware Series terug in Europe/Amsterdam.
    Retourneert None bij lege response.
    """
    s = client.query_day_ahead_prices(eic, start=start, end=end)

    if s is None or len(s) == 0:
        return None

    # entsoe-py geeft meestal tz-aware terug, maar we vangen het af
    if getattr(s.index, "tz", None) is None:
        s.index = s.index.tz_localize("UTC")

    # Normaliseer naar NL-tijd en sorteert
    s = s.tz_convert(TZ).sort_index()
    return s

def wait_for_day_ahead(
    api_key: str,
    zones: dict,
    target_date: pd.Timestamp,
    poll_seconds: int = 60,
    timeout_minutes: int = 120,
    primary_zone: str = "NL",
    fetch_all_zones_each_poll: bool = False,
    min_other_zones: int = 0,
    log_errors: bool = True,
    log_every_poll: bool = True,   # NIEUW: altijd een heartbeat logregel per poll
    max_error_len: int = 200,      # NIEUW: beperk error spam
):
    """
    Wacht tot day-ahead data voor primary_zone compleet is (DST-proof).

    Logging verbeteringen:
    - elke poll een heartbeat (tijd, attempt, waited, primary progress)
    - volledigheid per zone bij verandering
    - errors alleen bij verandering + ingekort
    """
    if not api_key:
        raise ValueError("api_key ontbreekt")

    if primary_zone not in zones:
        raise ValueError(f"primary_zone '{primary_zone}' zit niet in zones keys: {list(zones.keys())}")

    client = EntsoePandasClient(api_key=api_key)

    start = pd.Timestamp(target_date.date(), tz=TZ)
    end = start + pd.Timedelta(days=1)
    exp = _expected_hours(start, end)

    t0 = time.time()
    deadline = t0 + timeout_minutes * 60

    last_status = None
    last_errors = None
    attempt = 0

    def _count(v):
        return None if v is None else int(v.dropna().shape[0])

    def status_dict(out: dict) -> dict:
        return {k: _count(v) for k, v in out.items()}

    def _shorten_errors(errors: dict) -> dict:
        if not errors:
            return {}
        short = {}
        for k, v in errors.items():
            s = str(v)
            if len(s) > max_error_len:
                s = s[:max_error_len] + "…"
            short[k] = s
        return short

    def fetch_many(codes_eics):
        out = {}
        errors = {}
        for code, eic in codes_eics:
            try:
                out[code] = _fetch(client, eic, start, end)
            except Exception as e:
                out[code] = None
                errors[code] = repr(e)
        return out, errors

    print(f"[watcher] {_utc_ts()} start target_date={start.date()} primary={primary_zone} expected_hours={exp} poll={poll_seconds}s timeout={timeout_minutes}m fetch_all={fetch_all_zones_each_poll}")

    while time.time() < deadline:
        attempt += 1
        waited_sec = int(time.time() - t0)

        # 1) Poll-strategie: alleen primary of alles
        if fetch_all_zones_each_poll:
            out, errors = fetch_many(list(zones.items()))
        else:
            out = {k: None for k in zones.keys()}
            errors = {}
            code = primary_zone
            eic = zones[primary_zone]
            try:
                out[code] = _fetch(client, eic, start, end)
            except Exception as e:
                out[code] = None
                errors[code] = repr(e)

        # 2) Status & heartbeat
        st = status_dict(out)
        primary_n = st.get(primary_zone)

        # Heartbeat: altijd iets per poll, zodat GitHub Actions niet "stil" lijkt
        if log_every_poll:
            print(
                f"[watcher] {_utc_ts()} attempt={attempt} waited={waited_sec//60}m{waited_sec%60:02d}s "
                f"primary={primary_zone}:{primary_n}/{exp}",
                flush=True
            )

        # Detailstatus alleen bij verandering (minder ruis)
        if st != last_status:
            print(f"[watcher] {_utc_ts()} completeness expected {exp}: {st}", flush=True)
            last_status = st

        if log_errors:
            short_errors = _shorten_errors(errors)
            if short_errors and short_errors != last_errors:
                print(f"[watcher] {_utc_ts()} errors: {short_errors}", flush=True)
                last_errors = short_errors

        # 3) Check primary completeness (DST-proof)
        s_primary = out.get(primary_zone)
        if s_primary is not None and int(s_primary.dropna().shape[0]) >= exp:
            got = int(s_primary.dropna().shape[0])
            print(f"[watcher] {_utc_ts()} Primary zone '{primary_zone}' is compleet ({got}/{exp}).", flush=True)

            # 4) Als we niet elke poll alles haalden: haal nu 1x alles op voor return
            if not fetch_all_zones_each_poll:
                full_out, full_errors = fetch_many(list(zones.items()))
                if full_out.get(primary_zone) is None:
                    full_out[primary_zone] = s_primary

                if min_other_zones > 0:
                    others_ok = sum(
                        1 for k, v in full_out.items()
                        if k != primary_zone and v is not None and len(v.dropna()) > 0
                    )
                    if others_ok < min_other_zones:
                        print(
                            f"[watcher] {_utc_ts()} Primary compleet, maar slechts {others_ok} andere zones hebben data "
                            f"(min_other_zones={min_other_zones}). Poll verder...",
                            flush=True
                        )
                        time.sleep(poll_seconds)
                        continue

                if log_errors and full_errors:
                    print(f"[watcher] {_utc_ts()} errors (final fetch): {_shorten_errors(full_errors)}", flush=True)

                return full_out

            # 5) Als we sowieso elke poll alles haalden: eventueel min_other_zones check
            if min_other_zones > 0:
                others_ok = sum(
                    1 for k, v in out.items()
                    if k != primary_zone and v is not None and len(v.dropna()) > 0
                )
                if others_ok < min_other_zones:
                    print(
                        f"[watcher] {_utc_ts()} Primary compleet, maar slechts {others_ok} andere zones hebben data "
                        f"(min_other_zones={min_other_zones}). Poll verder...",
                        flush=True
                    )
                    time.sleep(poll_seconds)
                    continue

            return out

        time.sleep(poll_seconds)

    # Timeout: geef nuttige context mee
    waited_total = int(time.time() - t0)
    raise TimeoutError(
        f"Primary zone '{primary_zone}' was niet compleet binnen {timeout_minutes} min. "
        f"Expected={exp}. Waited={waited_total//60}m{waited_total%60:02d}s. "
        f"Laatst status={last_status}. Laatste errors={last_errors}."
    )
