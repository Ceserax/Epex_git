import time
import pandas as pd
from entsoe import EntsoePandasClient

TZ = "Europe/Amsterdam"

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
):
    """
    Wacht tot day-ahead data voor primary_zone compleet is (DST-proof).
    - fetch_all_zones_each_poll=False: eerst alleen primary_zone poll-en (sneller, minder load).
      Zodra primary_zone compleet is, halen we 1x alle zones op en returnen.
    - min_other_zones: optioneel minimum aantal andere zones dat niet-None moet zijn voordat we returnen.
      (Standaard 0: alleen primary_zone is leidend.)
    """
    if not api_key:
        raise ValueError("api_key ontbreekt")

    if primary_zone not in zones:
        raise ValueError(f"primary_zone '{primary_zone}' zit niet in zones keys: {list(zones.keys())}")

    client = EntsoePandasClient(api_key=api_key)

    start = pd.Timestamp(target_date.date(), tz=TZ)
    end = start + pd.Timedelta(days=1)
    exp = _expected_hours(start, end)

    deadline = time.time() + timeout_minutes * 60
    last_status = None
    last_errors = None

    def status_dict(out: dict) -> dict:
        return {k: (None if v is None else int(v.dropna().shape[0])) for k, v in out.items()}

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

    while time.time() < deadline:
        # 1) Poll-strategie: alleen NL (primary) of alles
        if fetch_all_zones_each_poll:
            out, errors = fetch_many(list(zones.items()))
        else:
            # Alleen primary zone ophalen
            out = {k: None for k in zones.keys()}
            errors = {}

            code = primary_zone
            eic = zones[primary_zone]
            try:
                out[code] = _fetch(client, eic, start, end)
            except Exception as e:
                out[code] = None
                errors[code] = repr(e)

        # 2) Logging
        st = status_dict(out)
        if st != last_status:
            print(f"[watcher] completeness expected {exp}: {st}")
            last_status = st

        if log_errors:
            # log errors alleen als ze veranderen, anders wordt het te noisy
            if errors != last_errors and errors:
                print(f"[watcher] errors: {errors}")
                last_errors = errors

        # 3) Check primary completeness (DST-proof)
        s_primary = out.get(primary_zone)
        if s_primary is not None and int(s_primary.dropna().shape[0]) >= exp:
            print(f"[watcher] Primary zone '{primary_zone}' is compleet ({int(s_primary.dropna().shape[0])}/{exp}).")

            # 4) Als we niet elke poll alles haalden: haal nu 1x alles op voor de return
            if not fetch_all_zones_each_poll:
                full_out, full_errors = fetch_many(list(zones.items()))
                # Zet primary van de polling (die is compleet) over full_out als die daar None zou zijn
                if full_out.get(primary_zone) is None:
                    full_out[primary_zone] = s_primary

                # Optioneel: wacht tot X andere zones ook niet-None zijn
                if min_other_zones > 0:
                    others_ok = sum(1 for k, v in full_out.items() if k != primary_zone and v is not None and len(v.dropna()) > 0)
                    if others_ok < min_other_zones:
                        print(f"[watcher] Primary compleet, maar slechts {others_ok} andere zones hebben data (min_other_zones={min_other_zones}). Poll verder...")
                        time.sleep(poll_seconds)
                        continue

                if log_errors and full_errors:
                    print(f"[watcher] errors (final fetch): {full_errors}")

                return full_out

            # 5) Als we sowieso elke poll alles haalden: eventueel min_other_zones check
            if min_other_zones > 0:
                others_ok = sum(1 for k, v in out.items() if k != primary_zone and v is not None and len(v.dropna()) > 0)
                if others_ok < min_other_zones:
                    print(f"[watcher] Primary compleet, maar slechts {others_ok} andere zones hebben data (min_other_zones={min_other_zones}). Poll verder...")
                    time.sleep(poll_seconds)
                    continue

            return out

        time.sleep(poll_seconds)

    # Timeout: geef nuttige context mee
    raise TimeoutError(
        f"Primary zone '{primary_zone}' was niet compleet binnen {timeout_minutes} min. "
        f"Expected={exp}. Laatste status={last_status}. Laatste errors={last_errors}."
    )
