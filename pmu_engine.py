#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - Collecte PMU avec provenance."""
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
DATA = Path("data")
API = os.getenv(
    "PMU_API_BASE",
    "https://online.turfinfo.api.pmu.fr/rest/client/7"
).rstrip("/")


def obtenir(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "X1000-PHOENIX/2.0",
            "Accept": "application/json"
        }
    )
    with urllib.request.urlopen(req, timeout=18) as r:
        return json.load(r)


def entier(v):
    try:
        if isinstance(v, bool):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def musique(v):
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return " ".join(map(str, v))
    return ""


def collecter(jour=None):
    now = dt.datetime.now(PARIS)
    jour = jour or now.date()
    date_api = jour.strftime("%d%m%Y")
    programme_url = f"{API}/programme/{date_api}"

    rapport = {
        "date": jour.isoformat(),
        "collecte_a": now.isoformat(),
        "source": programme_url,
        "courses": [],
        "erreurs": []
    }

    try:
        programme = obtenir(programme_url)
        reunions = programme.get("programme", {}).get(
            "reunions", []
        )
        if not isinstance(reunions, list):
            raise ValueError("Format reunions incorrect")
    except Exception as e:
        rapport["erreurs"].append(
            f"Programme inaccessible: {e}"
        )
        return rapport

    for reunion in reunions:
        nr = entier(reunion.get("numOfficiel"))
        if not nr:
            continue

        hippodrome = reunion.get("hippodrome", {})
        if isinstance(hippodrome, dict):
            hippodrome = hippodrome.get("libelleLong", "")

        for info in reunion.get("courses", []):
            nc = entier(info.get("numOrdre"))
            if not nc:
                continue

            url = (
                f"{API}/programme/{date_api}"
                f"/R{nr}/C{nc}/participants"
            )

            try:
                participants = obtenir(url)
                if not isinstance(participants, list):
                    raise ValueError("Participants non disponibles")

                chevaux = []
                numeros = set()

                for p in participants:
                    n = entier(p.get("numPmu"))
                    if not n or n in numeros:
                        continue
                    numeros.add(n)

                    chevaux.append({
                        "numero": n,
                        "nom": p.get("nom", ""),
                        "non_partant": (
                            p.get("statut") == "NON_PARTANT"
                            or p.get("nonPartant") is True
                        ),
                        "musique": musique(p.get("musique")),
                        "gains": p.get("gainCarriere"),
                        "jockey": (
                            p.get("jockey", {})
                            if isinstance(p.get("jockey"), str)
                            else ""
                        ),
                        "source": url
                    })

                depart_ms = info.get("heureDepart")
                if not isinstance(depart_ms, (int, float)):
                    raise ValueError("Heure de depart absente")

                depart = dt.datetime.fromtimestamp(
                    depart_ms / 1000, PARIS
                ).isoformat()

                if not chevaux:
                    raise ValueError("Aucun participant valide")

                rapport["courses"].append({
                    "id": f"{jour.isoformat()}-R{nr}-C{nc}",
                    "reunion": nr,
                    "course": nc,
                    "hippodrome": hippodrome,
                    "nom": info.get("libelle", ""),
                    "depart": depart,
                    "partants": chevaux,
                    "source": url,
                    "collecte_a": now.isoformat()
                })

            except Exception as e:
                rapport["erreurs"].append(
                    f"R{nr}C{nc}: {e}"
                )

    return rapport


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    resultat = collecter()
    (DATA / "collecte.json").write_text(
        json.dumps(resultat, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(
        f"{len(resultat['courses'])} courses collectees, "
        f"{len(resultat['erreurs'])} erreurs"
    )
