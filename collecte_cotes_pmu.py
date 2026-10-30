#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — collecte consultative des rapports probables PMU.

Lit data/collecte.json et écrit uniquement data/publication_cotes_pmu.json.
Ne touche jamais aux moteurs, pronostics officiels, PV ou FIGÉs.

python collecte_cotes_pmu.py --self-test
python collecte_cotes_pmu.py
python collecte_cotes_pmu.py --date 2026-10-30
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SOURCE = DATA / "collecte.json"
OUTPUT = DATA / "publication_cotes_pmu.json"
PARIS = ZoneInfo("Europe/Paris")
API = os.environ.get(
    "PMU_API_BASE",
    "https://online.turfinfo.api.pmu.fr/rest/client/7"
).rstrip("/")
UA = "X1000-PHOENIX-COTES/2.0"
COURSE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})-R([1-9]\d*)-C([1-9]\d*)$"
)


def positif(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError, OverflowError):
        return None
    return round(x, 3) if math.isfinite(x) and x > 0 else None


def numero(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        texte = str(value).strip()
        n = int(texte)
        return n if n > 0 and texte.isdecimal() else None
    except (TypeError, ValueError, OverflowError):
        return None


def lire_participants(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("participants", "partants"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError(
        "Réponse PMU : liste des participants introuvable"
    )


def rapport_gagnant(participant):
    """Accepte uniquement les champs de rapport identifiés.

    Un rapport explicitement typé placé n'est pas traité
    comme un rapport gagnant.
    """
    for key in (
        "dernierRapportDirect",
        "rapportDirect",
        "rapportProbable"
    ):
        objet = participant.get(key)

        if isinstance(objet, dict):
            type_rapport = str(
                objet.get("typePari", objet.get("type", ""))
            ).upper()

            if type_rapport and not any(
                x in type_rapport
                for x in ("GAGNANT", "SIMPLE_GAGNANT")
            ):
                continue

            for champ in ("rapport", "valeur"):
                valeur = positif(objet.get(champ))
                if valeur is not None:
                    return valeur, key + "." + champ

        elif key == "rapportProbable":
            valeur = positif(objet)
            if valeur is not None:
                return valeur, key

    return None, None


def requete_json(url, tentatives=3):
    for i in range(tentatives):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json"
                }
            )
            with urlopen(req, timeout=15) as response:
                return json.load(response)

        except HTTPError as exc:
            if (
                exc.code not in
                (408, 429, 500, 502, 503, 504)
                or i == tentatives - 1
            ):
                raise

        except (URLError, TimeoutError, OSError):
            if i == tentatives - 1:
                raise

        time.sleep(1.5 * (i + 1))

    raise RuntimeError("Nombre de tentatives épuisé")


def depart_paris(course):
    if course.get("depart_verifie") is not True:
        return None

    texte = course.get("depart")
    if not isinstance(texte, str):
        return None

    try:
        valeur = dt.datetime.fromisoformat(
            texte.replace("Z", "+00:00")
        )
        return (
            valeur.astimezone(PARIS)
            if valeur.tzinfo is not None
            else None
        )
    except (ValueError, OverflowError):
        return None


def non_partants_connus(course):
    resultat = set()

    valeurs = course.get("non_partants", [])
    if not isinstance(valeurs, list):
        valeurs = []

    for valeur in valeurs:
        n = (
            numero(valeur.get("numero"))
            if isinstance(valeur, dict)
            else numero(valeur)
        )
        if n is not None:
            resultat.add(n)

    partants = course.get("partants", [])
    if not isinstance(partants, list):
        partants = []

    for cheval in partants:
        if (
            isinstance(cheval, dict)
            and cheval.get("non_partant") is True
        ):
            n = numero(cheval.get("numero"))
            if n is not None:
                resultat.add(n)

    return resultat


def construire(
    collecte,
    date_cible,
    instant,
    fetch=requete_json,
    pause=0.25
):
    if instant.tzinfo is None:
        raise ValueError(
            "L'heure de collecte doit contenir un fuseau horaire"
        )

    instant = instant.astimezone(PARIS)

    if (
        not isinstance(collecte, dict)
        or not isinstance(collecte.get("courses"), list)
    ):
        raise ValueError(
            "Collecte invalide : courses absentes"
        )

    if collecte.get("date") != date_cible:
        raise ValueError(
            "Date de collecte différente de la date demandée"
        )

    if collecte.get("statut") not in (
        None, "OK", "PARTIEL"
    ):
        raise ValueError(
            "Statut de collecte non exploitable"
        )

    resultats = []
    erreurs = []
    deja_vus = set()
    candidats = 0

    date_pmu = dt.date.fromisoformat(
        date_cible
    ).strftime("%d%m%Y")

    for course in collecte["courses"]:
        if not isinstance(course, dict):
            continue

        cid = course.get("id")
        match = (
            COURSE_RE.fullmatch(cid)
            if isinstance(cid, str)
            else None
        )

        if (
            not match
            or match.group(1) != date_cible
            or cid in deja_vus
        ):
            continue

        deja_vus.add(cid)

        if (
            course.get("localisation_france_verifiee")
            is not True
        ):
            continue

        depart = depart_paris(course)

        if (
            depart is None
            or depart.date().isoformat() != date_cible
            or depart <= instant
        ):
            continue

        candidats += 1

        reunion = match.group(2)
        course_num = match.group(3)

        url = (
            f"{API}/programme/{date_pmu}"
            f"/R{reunion}/C{course_num}/participants"
        )

        try:
            participants = lire_participants(fetch(url))

            if not participants:
                raise ValueError(
                    "Liste de participants vide"
                )

            connus_np = non_partants_connus(course)
            chevaux = []
            numeros = set()

            for p in participants:
                if not isinstance(p, dict):
                    continue

                n = (
                    numero(p.get("numPmu"))
                    or numero(p.get("numero"))
                )

                if n is None or n in numeros:
                    continue

                numeros.add(n)

                np = (
                    n in connus_np
                    or p.get("nonPartant") is True
                    or p.get("non_partant") is True
                )

                valeur, champ = (
                    (None, None)
                    if np
                    else rapport_gagnant(p)
                )

                chevaux.append({
                    "numero": n,
                    "nom": (
                        p.get("nom")
                        if isinstance(p.get("nom"), str)
                        else None
                    ),
                    "non_partant": np,
                    "rapport_probable_gagnant": valeur,
                    "champ_source": champ,
                    "statut": (
                        "NON_PARTANT"
                        if np
                        else (
                            "DISPONIBLE"
                            if valeur is not None
                            else "INDISPONIBLE"
                        )
                    )
                })

            if not chevaux:
                raise ValueError(
                    "Aucun participant identifiable"
                )

            chevaux.sort(
                key=lambda c: c["numero"]
            )

            disponibles = sum(
                c["rapport_probable_gagnant"] is not None
                for c in chevaux
            )

            resultats.append({
                "course_id": cid,
                "hippodrome": course.get("hippodrome"),
                "depart_paris": depart.isoformat(),
                "source": url,
                "releve_a_paris": (
                    dt.datetime.now(PARIS).isoformat()
                ),
                "type": (
                    "RAPPORT_PROBABLE_SIMPLE_GAGNANT_NON_CONFIRME"
                ),
                "chevaux": chevaux,
                "statut": (
                    "OK"
                    if disponibles
                    else "AUCUN_RAPPORT_DISPONIBLE"
                )
            })

        except (
            ValueError,
            TypeError,
            HTTPError,
            URLError,
            OSError,
            json.JSONDecodeError
        ) as exc:
            erreurs.append({
                "course_id": cid,
                "erreur": str(exc)[:240]
            })

        if pause > 0:
            time.sleep(pause)

    resultats.sort(
        key=lambda c: (
            c["depart_paris"],
            c["course_id"]
        )
    )

    return {
        "module": "collecte_cotes_pmu",
        "version": "2.0",
        "date": date_cible,
        "collecte_a_paris": instant.isoformat(),
        "source_type": "API_PMU_NON_OFFICIELLE",
        "unite": (
            "rapport probable décimal indicatif, non garanti"
        ),
        "courses": resultats,
        "erreurs": erreurs,
        "statistiques": {
            "courses_candidates": candidats,
            "courses_collectees": len(resultats),
            "courses_avec_rapports": sum(
                c["statut"] == "OK"
                for c in resultats
            ),
            "erreurs": len(erreurs)
        },
        "avertissement": (
            "Données non vérifiées en temps réel; "
            "aucun pronostic, PV ou FIGÉ modifié."
        )
    }


def publier(rapport):
    # Conserver la publication existante en l'absence
    # de rapports exploitables.
    if not any(
        c["statut"] == "OK"
        for c in rapport["courses"]
    ):
        raise ValueError(
            "Aucun rapport gagnant exploitable : "
            "publication conservée"
        )

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporaire = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=OUTPUT.parent,
            prefix=".cotes-",
            suffix=".tmp",
            delete=False
        ) as f:
            temporaire = Path(f.name)

            json.dump(
                rapport,
                f,
                ensure_ascii=False,
                indent=2,
                allow_nan=False
            )
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())

        os.replace(temporaire, OUTPUT)

    finally:
        if temporaire is not None:
            temporaire.unlink(
                missing_ok=True
            )


def self_test():
    assert positif("4,5") == 4.5
    assert positif(float("nan")) is None
    assert positif(True) is None
    assert numero("03") == 3

    assert rapport_gagnant({
        "rapportProbable": {
            "rapport": 5.2
        }
    })[0] == 5.2

    assert rapport_gagnant({
        "rapportProbable": {
            "type": "PLACE",
            "rapport": 2.1
        }
    })[0] is None

    assert rapport_gagnant({
        "cote": 3.4
    }) == (None, None)

    instant = dt.datetime(
        2026, 10, 30, 9,
        tzinfo=PARIS
    )

    course = {
        "id": "2026-10-30-R1-C2",
        "localisation_france_verifiee": True,
        "depart_verifie": True,
        "depart": "2026-10-30T14:00:00+01:00",
        "non_partants": [2]
    }

    source = {
        "date": "2026-10-30",
        "statut": "OK",
        "courses": [course]
    }

    def mock(_url):
        return {
            "participants": [
                {
                    "numPmu": 1,
                    "nom": "TEST A",
                    "rapportProbable": {
                        "rapport": 4.5
                    }
                },
                {
                    "numPmu": 2,
                    "nom": "TEST NP",
                    "rapportProbable": 9.0
                }
            ]
        }

    rapport = construire(
        source,
        "2026-10-30",
        instant,
        fetch=mock,
        pause=0
    )

    assert (
        rapport["statistiques"]["courses_avec_rapports"]
        == 1
    )

    chevaux = rapport["courses"][0]["chevaux"]

    assert (
        chevaux[0]["rapport_probable_gagnant"]
        == 4.5
    )

    assert (
        chevaux[1]["rapport_probable_gagnant"]
        is None
    )

    apres_depart = construire(
        source,
        "2026-10-30",
        instant.replace(hour=15),
        fetch=mock,
        pause=0
    )

    assert not apres_depart["courses"]

    print(
        "SELF-TEST OK : rapports, non-partants, "
        "dates et validations"
    )


def main():
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--date",
        help="AAAA-MM-JJ (défaut : aujourd'hui à Paris)"
    )

    parser.add_argument(
        "--self-test",
        action="store_true"
    )

    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    try:
        instant = dt.datetime.now(PARIS)

        date_cible = (
            dt.date.fromisoformat(
                args.date
            ).isoformat()
            if args.date
            else instant.date().isoformat()
        )

        with SOURCE.open(
            "r",
            encoding="utf-8-sig"
        ) as f:
            collecte = json.load(f)

        rapport = construire(
            collecte,
            date_cible,
            instant
        )

        publier(rapport)

        print(
            "Courses avec rapports : "
            f"{rapport['statistiques']['courses_avec_rapports']}"
        )
        print(
            f"Publication consultative : {OUTPUT}"
        )

        return 0

    except (
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError
    ) as exc:
        print(
            f"ERREUR : {exc}. "
            "Fichiers officiels inchangés.",
            file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
