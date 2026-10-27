#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X1000 PHOENIX — COLLECTEUR PMU 2.0
M1 à M5 — données réelles et traçables.

- Programme PMU
- Courses physiquement disputées en France
- Partants et non-partants
- Sources URL et empreintes SHA256
- Aucune note inventée
- Aucun résultat inventé
- Aucun faux FIGÉ
- Publication compatible avec publication.py

Python 3.12 — bibliothèque standard.
"""

import datetime as dt
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
BASE = "https://online.turfinfo.api.pmu.fr/rest/client/61"
DATA = Path("data")
DATA.mkdir(parents=True, exist_ok=True)

TIMEOUT = 25
MAX_COURSES = 250
MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def maintenant():
    return dt.datetime.now(PARIS)


def horodatage(ms):
    if type(ms) not in (int, float) or ms <= 0:
        raise ValueError("Horodatage PMU invalide")
    return dt.datetime.fromtimestamp(ms / 1000, PARIS)


def entier(valeur):
    if isinstance(valeur, bool):
        return None
    try:
        n = int(valeur)
        return n if n > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def texte(valeur):
    if isinstance(valeur, dict):
        return str(
            valeur.get("libelle")
            or valeur.get("libelleCourt")
            or valeur.get("nom")
            or valeur.get("code")
            or ""
        )
    return str(valeur) if valeur is not None else ""


def liste(valeur):
    return valeur if isinstance(valeur, list) else []


def lire(nom, defaut=None):
    chemin = DATA / nom
    if not chemin.exists():
        return defaut
    with chemin.open(encoding="utf-8") as f:
        return json.load(f)


def sauver(nom, objet):
    chemin = DATA / nom
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(
        chemin.suffix + ".tmp"
    )
    temporaire.write_text(
        json.dumps(
            objet,
            ensure_ascii=False,
            indent=2,
            allow_nan=False
        ) + "\n",
        encoding="utf-8"
    )
    os.replace(temporaire, chemin)


def empreinte_octets(contenu):
    return hashlib.sha256(contenu).hexdigest()


def api(chemin):
    url = BASE + chemin
    requete = urllib.request.Request(
        url,
        headers={
            "User-Agent": "X1000-Phoenix/2.0",
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(
        requete, timeout=TIMEOUT
    ) as reponse:
        contenu = reponse.read()
        adresse_finale = reponse.geturl()
        type_contenu = reponse.headers.get(
            "Content-Type", ""
        )

    if not adresse_finale.startswith("https://"):
        raise ValueError("Source non HTTPS")

    if "json" not in type_contenu.lower():
        raise ValueError("Réponse non JSON")

    objet = json.loads(contenu.decode("utf-8"))

    return objet, {
        "url": adresse_finale,
        "sha256": empreinte_octets(contenu),
        "collecte_a": maintenant().isoformat(),
        "type": "API_PMU"
    }


def pays_francais(reunion):
    hippo = reunion.get("hippodrome") or {}
    if not isinstance(hippo, dict):
        return False

    pays = hippo.get("pays") or reunion.get("pays")

    if isinstance(pays, dict):
        pays = (
            pays.get("code")
            or pays.get("libelle")
        )

    return str(pays or "").upper().strip() in (
        "FR", "FRA", "FRANCE"
    )


def programme_courses(objet, date):
    if not isinstance(objet, dict):
        raise ValueError("Programme PMU invalide")

    programme = objet.get("programme", objet)
    if not isinstance(programme, dict):
        raise ValueError("Structure programme invalide")

    reunions = programme.get("reunions")
    if not isinstance(reunions, list):
        raise ValueError("Réunions PMU indisponibles")

    courses = []

    for reunion in reunions:
        if not isinstance(reunion, dict):
            continue

        if not pays_francais(reunion):
            continue

        rn = entier(
            reunion.get("numOfficiel")
            or reunion.get("numReunion")
        )
        if rn is None:
            continue

        hippo = reunion.get("hippodrome") or {}
        nom_hippo = texte(
            hippo.get("libelleCourt")
            or hippo.get("libelleLong")
        )

        for course in liste(reunion.get("courses")):
            if not isinstance(course, dict):
                continue

            cn = entier(
                course.get("numOrdre")
                or course.get("numCourse")
            )
            depart_ms = entier(
                course.get("heureDepart")
            )

            if cn is None or depart_ms is None:
                continue

            courses.append({
                "id": f"{date}-R{rn}-C{cn}",
                "date": date,
                "reunion": rn,
                "course": cn,
                "hippodrome": nom_hippo,
                "nom": texte(course.get("libelle")),
                "depart": horodatage(
                    depart_ms
                ).isoformat(),
                "discipline": texte(
                    course.get("discipline")
                ),
                "partants": [],
                "moteurs": [],
                "statut": "PARTANTS_NON_CHARGES"
            })

    return courses[:MAX_COURSES]


def extraire_partants(objet):
    if isinstance(objet, dict):
        participants = objet.get("participants")
    else:
        participants = objet

    if not isinstance(participants, list):
        raise ValueError("Participants indisponibles")

    resultat = []
    numeros = set()

    for p in participants:
        if not isinstance(p, dict):
            continue

        numero = entier(p.get("numPmu"))

        if numero is None or numero in numeros:
            continue

        numeros.add(numero)

        resultat.append({
            "numero": numero,
            "nom": texte(p.get("nom")),
            "musique": texte(p.get("musique")),
            "jockey": texte(
                p.get("jockey") or p.get("driver")
            ),
            "entraineur": texte(
                p.get("entraineur")
            ),
            "non_partant": (
                p.get("nonPartant") is True
            )
        })

    if not resultat:
        raise ValueError("Aucun partant exploitable")

    return resultat


def course_compatible_phoenix(course):
    """
    Ne transmettre aucune note inventée.
    Les cinq critères doivent être fournis
    par une étude documentée indépendante.
    """
    partants = course.get("partants", [])

    if len([
        p for p in partants
        if not p.get("non_partant")
    ]) < 5:
        return False

    criteres = (
        "forme",
        "aptitude",
        "regularite",
        "entourage",
        "valeur"
    )

    for cheval in partants:
        if cheval.get("non_partant"):
            continue

        notes = cheval.get("notes")

        if not isinstance(notes, dict):
            return False

        for critere in criteres:
            valeur = notes.get(critere)
            if type(valeur) not in (int, float):
                return False
            if not 0 <= valeur <= 10:
                return False

    return True


def collecter(date):
    code = dt.datetime.strptime(
        date, "%Y-%m-%d"
    ).strftime("%d%m%Y")

    objet, provenance = api(
        f"/programme/{code}?specialisation=INTERNET"
    )

    courses = programme_courses(objet, date)
    erreurs = []

    for course in courses:
        rn = course["reunion"]
        cn = course["course"]

        chemin = (
            f"/programme/{code}/R{rn}/C{cn}"
            "/participants?specialisation=INTERNET"
        )

        try:
            participants, source = api(chemin)
            partants = extraire_partants(
                participants
            )

            course["partants"] = partants
            course["nombre_partants"] = sum(
                not p["non_partant"]
                for p in partants
            )
            course["source"] = source["url"]
            course["provenance"] = {
                "programme": provenance,
                "participants": source
            }

            # Les moteurs M1-M5 ne sont pas
            # alimentés par des notes fictives.
            course["moteurs"] = []
            course["statut"] = (
                "DONNEES_PMU_COLLECTEES_"
                "ANALYSE_NON_DISPONIBLE"
            )

        except (
            urllib.error.URLError,
            ValueError,
            TypeError,
            KeyError,
            OSError
        ) as exc:
            course["statut"] = "ERREUR_SOURCE"
            course["erreur"] = str(exc)
            course["source"] = provenance["url"]

            erreurs.append({
                "course_id": course["id"],
                "erreur": str(exc)
            })

    # Ne pas effacer les archives PV/FIGÉS.
    # Ne pas fabriquer de FIGÉ expérimental.
    sauver("courses.json", {
        "date": date,
        "actualise": maintenant().isoformat(),
        "source_programme": provenance,
        "courses": courses
    })

    # Écarter l'ancien course.json s'il est
    # invalide : publication.py ne doit pas
    # l'analyser comme une nouvelle course.
    entree = DATA / "course.json"

    if entree.exists():
        try:
            ancien = lire("course.json")
            if (
                not isinstance(ancien, dict)
                or not ancien.get("source", "").startswith(
                    "https://"
                )
                or not course_compatible_phoenix(
                    ancien
                )
            ):
                entree.unlink()
        except (
            ValueError, TypeError,
            AttributeError, OSError
        ):
            if entree.exists():
                entree.unlink()

    return {
        "courses": len(courses),
        "erreurs": erreurs,
        "source": provenance
    }


def main():
    date = maintenant().date().isoformat()

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "date": date,
        "execution": maintenant().isoformat(),
        "statut": "ERREUR",
        "courses": 0,
        "erreurs": []
    }

    try:
        resultat = collecter(date)
        rapport["courses"] = resultat["courses"]
        rapport["erreurs"] = resultat["erreurs"]
        rapport["source"] = resultat["source"]

        if rapport["courses"] == 0:
            rapport["statut"] = "AUCUNE_COURSE"
        elif rapport["erreurs"]:
            rapport["statut"] = "PARTIEL"
        else:
            rapport["statut"] = "COLLECTE_OK"

    except Exception as exc:
        rapport["erreurs"].append(str(exc))

    sauver("rapport.json", rapport)

    print(json.dumps(
        rapport,
        ensure_ascii=False,
        indent=2
    ))

    if rapport["statut"] == "ERREUR":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
