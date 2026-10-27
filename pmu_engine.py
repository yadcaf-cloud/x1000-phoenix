#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X1000 PHOENIX — M1 A M5
Collecte PMU, analyse, FIGES, audits.

Donnees reelles uniquement.
Scores heuristiques explicites.
Aucun resultat ou pari invente.

Compatible Python 3.12 et GitHub Actions.
"""

import datetime as dt
import json
import math
import re
import urllib.request
import urllib.error
from pathlib import Path
from zoneinfo import ZoneInfo

from phoenix import (
    figer, auditer, verifier_fige,
    lire, ecrire, maintenant
)

PARIS = ZoneInfo("Europe/Paris")
DATA = Path("data")
BASE = "https://online.turfinfo.api.pmu.fr/rest/client/61"

DATA.mkdir(parents=True, exist_ok=True)

# Poids forme recente / regularite / gains.
# Ces poids ne sont pas des probabilites.
POIDS = {
    "M1": (0.60, 0.30, 0.10),
    "M2": (0.35, 0.55, 0.10),
    "M3": (0.45, 0.20, 0.35),
    "M4": (0.25, 0.35, 0.40),
    "M5": (0.40, 0.40, 0.20)
}

CRITERES = (
    "forme_recente",
    "regularite",
    "gains_carriere"
)


def api(chemin):
    url = BASE + chemin

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "X1000-Phoenix/3.0",
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(
        req, timeout=25
    ) as response:
        if not response.geturl().startswith("https://"):
            raise ValueError("Source non securisee")
        contenu = response.read()

    return json.loads(contenu.decode("utf-8")), url


def entier(v):
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
        return n if n > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def nombre(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        n = float(v)
        if math.isfinite(n) and n >= 0:
            return n
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def texte(v):
    if isinstance(v, dict):
        return str(
            v.get("libelle")
            or v.get("libelleCourt")
            or v.get("nom")
            or v.get("code")
            or ""
        )
    return str(v) if v is not None else ""


def liste(v):
    return v if isinstance(v, list) else []


def horodatage(ms):
    n = entier(ms)
    if n is None:
        raise ValueError("Heure de depart invalide")
    return dt.datetime.fromtimestamp(n / 1000, PARIS)


def source_francaise(reunion):
    hippo = reunion.get("hippodrome") or {}
    if not isinstance(hippo, dict):
        return False

    pays = hippo.get("pays") or reunion.get("pays")
    if isinstance(pays, dict):
        pays = pays.get("code") or pays.get("libelle")

    return str(pays or "").upper().strip() in (
        "FR", "FRA", "FRANCE"
    )


def programme(date):
    code = date.strftime("%d%m%Y")
    objet, url = api(
        f"/programme/{code}?specialisation=INTERNET"
    )

    bloc = objet.get("programme", objet)
    if not isinstance(bloc, dict):
        raise ValueError("Programme invalide")

    reunions = bloc.get("reunions")
    if not isinstance(reunions, list):
        raise ValueError("Reunions indisponibles")

    courses = []

    for reunion in reunions:
        if not isinstance(reunion, dict):
            continue
        if not source_francaise(reunion):
            continue

        rn = entier(
            reunion.get("numOfficiel")
            or reunion.get("numReunion")
        )
        if rn is None:
            continue

        hippo = reunion.get("hippodrome") or {}
        nom = texte(
            hippo.get("libelleCourt")
            or hippo.get("libelleLong")
        )

        for c in liste(reunion.get("courses")):
            if not isinstance(c, dict):
                continue

            cn = entier(
                c.get("numOrdre")
                or c.get("numCourse")
            )
            ms = entier(c.get("heureDepart"))

            if cn is None or ms is None:
                continue

            courses.append({
                "id": (
                    f"{date.isoformat()}-R{rn}-C{cn}"
                ),
                "reunion": rn,
                "course": cn,
                "hippodrome": nom,
                "depart": horodatage(ms).isoformat(),
                "nom": texte(c.get("libelle")),
                "source_programme": url
            })

    return courses


def participants(course, date):
    code = date.strftime("%d%m%Y")

    chemin = (
        f"/programme/{code}/"
        f"R{course['reunion']}/"
        f"C{course['course']}/participants"
        "?specialisation=INTERNET"
    )

    objet, url = api(chemin)

    brut = (
        objet.get("participants")
        if isinstance(objet, dict)
        else objet
    )

    if not isinstance(brut, list):
        raise ValueError("Participants absents")

    chevaux = []
    numeros = set()

    for p in brut:
        if not isinstance(p, dict):
            continue

        n = entier(p.get("numPmu"))

        if n is None or n in numeros:
            continue

        numeros.add(n)

        chevaux.append({
            "numero": n,
            "nom": texte(p.get("nom")),
            "musique": texte(p.get("musique")),
            "gains": nombre(p.get("gainCarriere")),
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

    return chevaux, url


def rangs_musique(musique):
    """
    Lecture prudente des rangs dans la musique.

    Exemple: 1a2a3a -> [1,2,3].
    0 = rang non classe dans les dix premiers.
    D, A, T et autres codes non classes
    ne sont pas convertis en classements.

    Les musiques non interpretables sont exclues.
    """
    s = str(musique or "").lower()

    if not s:
        return []

    # Exige des codes de discipline reconnus.
    tokens = re.findall(
        r"(\d{1,2})([apmh])", s
    )

    rangs = []

    for chiffre, discipline in tokens[:5]:
        n = int(chiffre)
        if n == 0:
            n = 11
        if 1 <= n <= 11:
            rangs.append(n)

    return rangs


def indicateurs(chevaux):
    actifs = [
        c for c in chevaux
        if not c["non_partant"]
    ]

    # Pour comparer les chevaux, les deux
    # variables doivent etre disponibles.
    # Ne jamais remplacer les valeurs absentes
    # par une note moyenne fictive.
    if len(actifs) < 5:
        return []

    if any(
        c["gains"] is None
        or not rangs_musique(c["musique"])
        for c in actifs
    ):
        return []

    maximum = max(c["gains"] for c in actifs)

    if maximum <= 0:
        return []

    resultat = []

    for c in actifs:
        rangs = rangs_musique(c["musique"])

        # Plus le rang est faible,
        # meilleur est l'indicateur.
        points = [
            max(0, 11 - r) / 10
            for r in rangs
        ]

        forme = sum(points) / len(points)

        # Regularite : proportion des
        # rangs connus dans les cinq premiers.
        regularite = sum(
            r <= 5 for r in rangs
        ) / len(rangs)

        gains = c["gains"] / maximum

        resultat.append({
            "numero": c["numero"],
            "forme_recente": round(forme, 6),
            "regularite": round(regularite, 6),
            "gains_carriere": round(gains, 6),
            "observations": len(rangs)
        })

    return resultat


def analyser_course(course, chevaux, source):
    profils = indicateurs(chevaux)

    if len(profils) < 5:
        return None

    instant = maintenant()
    sorties = []

    for moteur, poids in POIDS.items():
        scores = []

        for p in profils:
            score = sum(
                p[critere] * coefficient
                for critere, coefficient
                in zip(CRITERES, poids)
            )

            scores.append({
                "numero": p["numero"],
                "score": round(score, 6)
            })

        scores.sort(
            key=lambda x: (
                -x["score"], x["numero"]
            )
        )

        ordre = [
            s["numero"] for s in scores[:5]
        ]

        ecart = (
            scores[0]["score"]
            - scores[1]["score"]
        )

        sorties.append({
            "moteur": moteur,
            "gagnant_espere": ordre[0],
            "meilleur_place": ordre[1],
            "ordre_espere": ordre,
            "pari_retenu": None,
            "qualification": (
                "VERT" if ecart >= 0.05
                else "JAUNE"
            ),
            "validation": "EXPERIMENTAL",
            "heure_paris": instant.isoformat(),
            "ecart_scores": round(ecart, 6),
            "scores": scores
        })

    return {
        "logiciel": "X1000 PHOENIX",
        "course_id": course["id"],
        "hippodrome": course["hippodrome"],
        "depart": course["depart"],
        "source": source,
        "analyse_a": instant.isoformat(),
        "nombre_partants": len(profils),
        "moteurs": sorties,
        "statut": "ANALYSE_EXPERIMENTALE",
        "indicateurs": profils,
        "methode": {
            "variables": list(CRITERES),
            "poids": {
                k: list(v)
                for k, v in POIDS.items()
            },
            "notes_inventees": False,
            "probabilites_calibrees": False
        },
        "avertissement": (
            "Classement heuristique experimental. "
            "La musique ne capture pas toutes les "
            "performances. Les gains dependent "
            "notamment de la carriere et ne sont "
            "pas une mesure directe de la forme. "
            "Aucune garantie de resultat."
        )
    }


def figes_existants():
    resultat = []

    dossier = DATA / "figes"
    if not dossier.exists():
        return resultat

    for chemin in sorted(dossier.glob("*.json")):
        try:
            objet = lire(chemin)
            verifier_fige(objet)
            resultat.append(objet)
        except (
            ValueError, KeyError,
            TypeError, OSError
        ) as exc:
            print("FIGE rejete :", chemin, exc)

    return resultat


def traiter_course(course, date):
    chevaux, url = participants(course, date)

    course["partants"] = chevaux
    course["source"] = url
    course["nombre_partants"] = sum(
        not c["non_partant"]
        for c in chevaux
    )

    depart = dt.datetime.fromisoformat(
        course["depart"]
    )

    secondes = (
        depart - maintenant()
    ).total_seconds()

    anciens = figes_existants()

    existant = next(
        (
            f for f in anciens
            if f["rapport"]["course_id"]
            == course["id"]
        ),
        None
    )

    if existant is not None:
        course["moteurs"] = (
            existant["rapport"]["moteurs"]
        )
        course["statut"] = "FIGE_VERIFIE"
        return course

    # Pas de nouvelle prediction apres depart.
    if secondes <= 0:
        course["moteurs"] = []
        course["statut"] = "COURSE_DEMARREE"
        return course

    analyse = analyser_course(
        course, chevaux, url
    )

    if analyse is None:
        course["moteurs"] = []
        course["statut"] = (
            "DONNEES_INSUFFISANTES"
        )
        return course

    course["moteurs"] = analyse["moteurs"]
    course["statut"] = (
        "ANALYSE_EXPERIMENTALE"
    )

    # FIGE uniquement dans les 20 minutes
    # avant depart, via phoenix.py.
    # Pas de verrou apres le depart.
    if 0 < secondes <= 1200:
        document = figer(analyse)

        if document is not None:
            verifier_fige(document)
            course["statut"] = "FIGE_VERIFIE"
            course["moteurs"] = (
                document["rapport"]["moteurs"]
            )

    return course


def audits_officiels():
    """
    Aucun audit sans arrivee definitive
    avec URL de provenance.
    """
    chemin = DATA / "arrivees_officielles.json"

    if not chemin.exists():
        return

    objet = lire(chemin)

    if not isinstance(objet, dict):
        return

    arrivees = liste(objet.get("courses"))
    figes = figes_existants()

    for arrivee in arrivees:
        if not isinstance(arrivee, dict):
            continue

        if arrivee.get("statut") != "definitive":
            continue

        source = arrivee.get("source", "")
        if not isinstance(source, str):
            continue
        if not source.startswith("https://"):
            continue

        cid = arrivee.get("course_id")

        for f in figes:
            if f["rapport"]["course_id"] != cid:
                continue

            bilan = auditer(f, arrivee)

            dossier = DATA / "audits"
            dossier.mkdir(
                parents=True, exist_ok=True
            )

            nom = re.sub(
                r"[^A-Za-z0-9_-]",
                "_", str(cid)
            )

            cible = dossier / (nom + ".json")

            if not cible.exists():
                ecrire(cible, bilan)


def main():
    instant = maintenant()
    date = instant.date()

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "version": "M1-M5-3.0",
        "execution": instant.isoformat(),
        "date": date.isoformat(),
        "statut": "ERREUR",
        "courses": 0,
        "analyses": 0,
        "figes_verifies": 0,
        "erreurs": []
    }

    try:
        courses = programme(date)
        sorties = []

        for course in courses:
            try:
                resultat = traiter_course(
                    course, date
                )
                sorties.append(resultat)

            except (
                ValueError, TypeError,
                KeyError, OSError,
                urllib.error.URLError
            ) as exc:
                course["moteurs"] = []
                course["statut"] = "ERREUR_SOURCE"
                course["erreur"] = str(exc)
                sorties.append(course)

                rapport["erreurs"].append({
                    "course": course["id"],
                    "erreur": str(exc)
                })

        rapport["courses"] = len(sorties)
        rapport["analyses"] = sum(
            bool(c.get("moteurs"))
            for c in sorties
        )
        rapport["figes_verifies"] = sum(
            c.get("statut") == "FIGE_VERIFIE"
            for c in sorties
        )

        ecrire(DATA / "courses.json", {
            "date": date.isoformat(),
            "actualise": maintenant().isoformat(),
            "courses": sorties
        })

        # Ne pas recreer de course.json :
        # publication.py doit utiliser directement
        # les courses deja analysees.
        ancien = DATA / "course.json"

        if ancien.exists():
            # On ne supprime pas une archive.
            # Seule une entree de travail invalide
            # peut etre ecartee.
            try:
                from phoenix import valider_course
                valider_course(lire(ancien))
            except (
                ValueError, TypeError,
                KeyError, OSError
            ):
                ancien.rename(
                    DATA / "course_ancien_invalide.json"
                )

        audits_officiels()

        rapport["statut"] = (
            "PARTIEL" if rapport["erreurs"]
            else "COLLECTE_OK"
        )

    except Exception as exc:
        rapport["erreurs"].append(str(exc))

    ecrire(DATA / "rapport.json", rapport)

    print(json.dumps(
        rapport,
        ensure_ascii=False,
        indent=2
    ))

    if rapport["statut"] == "ERREUR":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
