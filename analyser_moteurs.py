#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — analyses heuristiques M1–M5, sans validation fictive."""

import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "publication_courses.json"
DEST = ROOT / "data" / "publication_analyses.json"
MOTEURS = ("M1", "M2", "M3", "M4", "M5")


def musique(texte):
    """Lire jusqu'à dix classements chiffrés récents."""
    texte = re.sub(r"\(\d{2,4}\)", "", str(texte or ""))
    return [
        int(n)
        for n, _ in re.findall(
            r"(\d+|[AaDdTtJj])([pPhHsSmMaA])", texte
        )
        if n.isdigit() and int(n) > 0
    ][:10]


def scores(cheval):
    rangs = musique(cheval.get("musique"))
    if not rangs:
        return None

    points = [
        max(0.0, 12 - min(n, 12)) / 11
        for n in rangs
    ]
    poids = (0.5, 0.3, 0.2)[:min(3, len(points))]
    forme = sum(
        p * w for p, w in zip(points, poids)
    ) / sum(poids)

    regularite = sum(n <= 3 for n in rangs) / len(rangs)
    victoires = sum(n == 1 for n in rangs) / len(rangs)
    constance = sum(points) / len(points)
    confiance = min(1.0, len(rangs) / 5)

    return {
        "M1": .75 * forme + .25 * constance,
        "M2": .75 * regularite + .25 * constance,
        "M3": .65 * victoires + .35 * forme,
        "M4": .60 * regularite + .25 * constance
              + .15 * confiance,
        "M5": .30 * forme + .30 * regularite
              + .20 * victoires + .20 * confiance,
    }


def _instant(valeur=None):
    if valeur is None:
        return dt.datetime.now(dt.timezone.utc)

    if isinstance(valeur, str):
        valeur = dt.datetime.fromisoformat(
            valeur.replace("Z", "+00:00")
        )

    if (
        not isinstance(valeur, dt.datetime)
        or valeur.tzinfo is None
        or valeur.utcoffset() is None
    ):
        raise ValueError("Date/heure sans fuseau horaire")

    return valeur.astimezone(dt.timezone.utc)


def _numero(valeur):
    if type(valeur) is int and valeur > 0:
        return valeur

    if (
        isinstance(valeur, str)
        and re.fullmatch(r"[1-9]\d*", valeur.strip())
    ):
        return int(valeur.strip())

    raise ValueError("Numéro de cheval invalide")


def _non_partant(cheval):
    return (
        cheval.get("non_partant") is True
        or str(cheval.get("statut", "")).strip().upper()
        in ("NON_PARTANT", "NON-PARTANT", "NP")
    )


def analyser(course, instant=None):
    """Analyser une course sans créer de FIGÉ."""

    if not isinstance(course, dict):
        raise ValueError("Course invalide")

    cid = course.get("id") or course.get("course_id")
    if (
        cid is None
        or isinstance(cid, bool)
        or not str(cid).strip()
    ):
        raise ValueError("Identifiant de course absent")

    depart_str = course.get("depart")
    if not isinstance(depart_str, str):
        raise ValueError("Départ absent")

    depart = _instant(depart_str)
    maintenant = _instant(instant)

    bruts = course.get("partants")
    if not isinstance(bruts, list):
        raise ValueError("Liste des partants absente")

    numeros = set()
    partants = []

    for cheval in bruts:
        if not isinstance(cheval, dict):
            raise ValueError("Fiche cheval invalide")

        numero = _numero(cheval.get("numero"))

        if numero in numeros:
            raise ValueError(
                f"Numéro dupliqué : {numero}"
            )

        numeros.add(numero)

        if not _non_partant(cheval):
            partants.append((numero, cheval))

    candidats = []

    for numero, cheval in partants:
        valeurs = scores(cheval)

        if valeurs is not None:
            candidats.append({
                "numero": numero,
                "nom": cheval.get("nom", ""),
                "scores": valeurs,
            })

    moteurs = []

    for nom in MOTEURS:
        ordre = sorted(
            candidats,
            key=lambda c: (
                -c["scores"][nom],
                c["numero"]
            )
        )

        top = [c["numero"] for c in ordre[:5]]

        moteurs.append({
            "moteur": nom,
            "gagnant_espere": top[0] if top else None,
            "meilleur_place": (
                top[1] if len(top) > 1 else None
            ),
            "ordre_espere": top,
            "ordre_arrivee_espere": top,
            "classement_complet": [
                c["numero"] for c in ordre
            ],
            "scores": {
                str(c["numero"]): round(
                    c["scores"][nom], 6
                )
                for c in ordre
            },
            "qualification": "ETUDE_NON_VALIDEE",
            "pari_retenu": None,
            "validation": "NON_FIGE",
        })

    verifie = (
        course.get("localisation_france_verifiee") is True
        and course.get("depart_verifie") is True
    )

    pre_depart = maintenant < depart

    return {
        "id": str(cid),
        "course_id": str(cid),
        "hippodrome": course.get("hippodrome"),
        "depart": depart_str,
        "source": course.get("source"),
        "analyse_a": maintenant.isoformat(),
        "nombre_partants": len(partants),
        "chevaux_evalues": len(candidats),
        "moteurs": moteurs,
        "statut": (
            "ANALYSE_EXPLORATOIRE"
            if candidats
            else "DONNEES_INSUFFISANTES"
        ),
        "qualification": "ETUDE_NON_VALIDEE",
        "validation": "NON_FIGE",
        "fige": False,
        "pari_officiel": False,
        "eligible_fige": bool(
            pre_depart
            and verifie
            and len(candidats) >= 2
        ),
        "avertissement": (
            "Classements heuristiques fondés uniquement "
            "sur la musique. Les indicateurs de vérification "
            "proviennent des données source et ne constituent "
            "pas une vérification indépendante. "
            "Aucune probabilité calibrée, validation officielle "
            "ou garantie de gain."
        ),
    }


def _ecrire_atomique(chemin, document):
    chemin.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    tmp = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=chemin.parent,
            prefix=".analyses_",
            suffix=".tmp",
            delete=False
        ) as fichier:
            tmp = Path(fichier.name)

            json.dump(
                document,
                fichier,
                ensure_ascii=False,
                indent=2,
                allow_nan=False
            )
            fichier.write("\n")
            fichier.flush()
            os.fsync(fichier.fileno())

        os.replace(tmp, chemin)

    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def main():
    if not SOURCE.is_file():
        raise SystemExit(
            f"Fichier PMU introuvable : {SOURCE}"
        )

    try:
        donnees = json.loads(
            SOURCE.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"Lecture PMU impossible : {exc}"
        ) from exc

    if (
        not isinstance(donnees, dict)
        or not isinstance(donnees.get("courses"), list)
    ):
        raise SystemExit(
            "Format incorrect : courses doit être une liste"
        )

    instant = _instant()
    analyses = []
    erreurs = []
    ignorees = 0

    for course in donnees["courses"]:
        try:
            if not isinstance(course, dict):
                raise ValueError("Course invalide")

            if (
                course.get(
                    "localisation_france_verifiee"
                ) is not True
                or course.get("depart_verifie") is not True
            ):
                ignorees += 1
                continue

            analyses.append(analyser(course, instant))

        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError
        ) as exc:
            erreurs.append({
                "id": (
                    course.get("id")
                    or course.get("course_id")
                ) if isinstance(course, dict) else None,
                "erreur": str(exc),
            })

    payload = {
        "genere_a": instant.isoformat(),
        "version": "M1-M5-heuristique-3",
        "analyses": analyses,
        "erreurs": erreurs,
        "courses_ignorees": ignorees,
    }

    _ecrire_atomique(DEST, payload)

    print(
        f"{len(analyses)} courses analysées, "
        f"{ignorees} ignorées, "
        f"{len(erreurs)} erreurs : {DEST}"
    )


if __name__ == "__main__":
    main()
