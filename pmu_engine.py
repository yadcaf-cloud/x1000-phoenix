#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - Collecte PMU vérifiable."""

import datetime as dt
import json
import os
import re
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
            "User-Agent": "Mozilla/5.0 X1000-PHOENIX/2.1",
            "Accept": "application/json"
        }
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status != 200:
            raise ValueError(f"HTTP {r.status}")
        return json.load(r)


def entier(v):
    try:
        if isinstance(v, bool) or v is None:
            return None
        n = int(v)
        return n if n >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def nombre(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        if isinstance(v, str):
            v = re.sub(r"[\s\u00a0\u202f€]", "", v)
            v = v.replace(",", ".")
        n = float(v)
        if not (0 <= n < float("inf")):
            return None
        return n
    except (TypeError, ValueError, OverflowError):
        return None


def texte(v):
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        for cle in ("nom", "libelleLong", "libelle", "name"):
            if isinstance(v.get(cle), str):
                return v[cle].strip()
    return ""


def musique(v):
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return " ".join(str(x) for x in v if x is not None)
    return ""


def depart_paris(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            valeur = float(v)
            if valeur <= 0:
                return None
            if valeur > 100000000000:
                valeur /= 1000
            return dt.datetime.fromtimestamp(
                valeur, PARIS
            ).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(v, str):
        try:
            instant = dt.datetime.fromisoformat(
                v.replace("Z", "+00:00")
            )
            if instant.tzinfo is None:
                return None
            return instant.astimezone(PARIS).isoformat()
        except ValueError:
            return None
    return None


def normaliser_participant(p, url):
    if not isinstance(p, dict):
        return None

    numero = entier(p.get("numPmu"))
    if numero is None or numero < 1:
        return None

    nom = texte(p.get("nom"))
    if not nom:
        return None

    statut = str(p.get("statut") or "").upper()
    non_partant = (
        statut in ("NON_PARTANT", "NONPARTANT", "NP")
        or p.get("nonPartant") is True
    )

    gains = nombre(
        p.get("gainCarriere", p.get("gains"))
    )

    return {
        "numero": numero,
        "nom": nom,
        "non_partant": non_partant,
        "musique": musique(p.get("musique")),
        "gains": gains,
        "jockey": texte(p.get("jockey")),
        "driver": texte(p.get("driver")),
        "entraineur": texte(p.get("entraineur")),
        "source": url
    }


def collecter(jour=None):
    now = dt.datetime.now(PARIS)
    jour = jour or now.date()

    if isinstance(jour, str):
        jour = dt.date.fromisoformat(jour)

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
        if not isinstance(programme, dict):
            raise ValueError("Programme JSON invalide")

        bloc = programme.get("programme", programme)
        if not isinstance(bloc, dict):
            raise ValueError("Structure programme invalide")

        reunions = bloc.get("reunions")
        if not isinstance(reunions, list):
            raise ValueError("Liste des reunions absente")

    except Exception as e:
        rapport["erreurs"].append(
            f"Programme inaccessible: {e}"
        )
        return rapport

    for reunion in reunions:
        if not isinstance(reunion, dict):
            continue

        nr = entier(
            reunion.get(
                "numOfficiel",
                reunion.get("numReunion")
            )
        )
        if nr is None or nr < 1:
            continue

        hippodrome = texte(reunion.get("hippodrome"))

        courses = reunion.get("courses", [])
        if not isinstance(courses, list):
            rapport["erreurs"].append(
                f"R{nr}: liste des courses invalide"
            )
            continue

        for info in courses:
            if not isinstance(info, dict):
                continue

            nc = entier(info.get("numOrdre"))
            if nc is None or nc < 1:
                continue

            url = (
                f"{API}/programme/{date_api}"
                f"/R{nr}/C{nc}/participants"
            )

            try:
                donnees = obtenir(url)

                if isinstance(donnees, list):
                    participants = donnees
                elif isinstance(donnees, dict):
                    participants = donnees.get("participants")
                else:
                    participants = None

                if not isinstance(participants, list):
                    raise ValueError(
                        "Liste des participants absente"
                    )

                chevaux = []
                numeros = set()

                for p in participants:
                    cheval = normaliser_participant(p, url)
                    if cheval is None:
                        continue

                    n = cheval["numero"]
                    if n in numeros:
                        continue

                    numeros.add(n)
                    chevaux.append(cheval)

                if not chevaux:
                    raise ValueError(
                        "Aucun participant exploitable"
                    )

                depart = depart_paris(
                    info.get("heureDepart")
                )

                if depart is None:
                    raise ValueError(
                        "Heure de depart non verifiable"
                    )

                rapport["courses"].append({
                    "id": (
                        f"{jour.isoformat()}-R{nr}-C{nc}"
                    ),
                    "reunion": nr,
                    "course": nc,
                    "hippodrome": hippodrome,
                    "nom": texte(info.get("libelle")),
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


def main():
    DATA.mkdir(parents=True, exist_ok=True)

    resultat = collecter()

    destination = DATA / "collecte.json"
    temporaire = DATA / "collecte.json.tmp"

    temporaire.write_text(
        json.dumps(
            resultat,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        ),
        encoding="utf-8"
    )
    os.replace(temporaire, destination)

    print(
        f"X1000 PHOENIX : "
        f"{len(resultat['courses'])} courses, "
        f"{len(resultat['erreurs'])} erreurs"
    )

    for erreur in resultat["erreurs"]:
        print("ALERTE:", erreur)


if __name__ == "__main__":
    main()
