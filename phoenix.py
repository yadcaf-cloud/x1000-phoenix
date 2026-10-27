#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — M1-M5, FIGES et audits consolides."""

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

PARIS = ZoneInfo("Europe/Paris")
DATA = Path("data")
BASE = DATA
FIGES = DATA / "figes"
AUDITS = DATA / "audits"
MARGE_MINUTES = 30

POIDS = {
    "M1": (5, 3),
    "M2": (3, 5),
    "M3": (4, 4),
    "M4": (6, 2),
    "M5": (2, 6),
}
MOTEURS = tuple(POIDS)


def maintenant():
    return dt.datetime.now(PARIS)


def date_paris(valeur):
    date = dt.datetime.fromisoformat(str(valeur))
    if date.tzinfo is None:
        raise ValueError("Fuseau horaire absent")
    return date.astimezone(PARIS)


def identifiant(valeur):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(valeur))


def lire(chemin):
    def uniques(paires):
        resultat = {}
        for cle, valeur in paires:
            if cle in resultat:
                raise ValueError("Cle JSON dupliquee : " + cle)
            resultat[cle] = valeur
        return resultat

    with Path(chemin).open(encoding="utf-8") as fichier:
        return json.load(
            fichier,
            object_pairs_hook=uniques,
            parse_constant=lambda x: (_ for _ in ()).throw(
                ValueError("Nombre JSON invalide : " + x)
            ),
        )


def ecrire(chemin, objet):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(chemin.suffix + ".tmp")
    temporaire.write_text(
        json.dumps(
            objet, ensure_ascii=False,
            indent=2, allow_nan=False
        ) + "\n",
        encoding="utf-8",
    )
    os.replace(temporaire, chemin)


def empreinte(objet):
    contenu = json.dumps(
        objet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(contenu).hexdigest()


def verifier_source(source):
    if not isinstance(source, str):
        return False
    try:
        url = urlsplit(source)
        return url.scheme == "https" and bool(url.hostname)
    except ValueError:
        return False


def rangs_musique(valeur):
    if not isinstance(valeur, str):
        return []
    rangs = []
    for token in re.findall(
        r"(?<!\d)(\d{1,2})[a-zA-Z]",
        valeur,
    ):
        rang = int(token)
        if 1 <= rang <= 20:
            rangs.append(rang)
    return rangs[:8]


def indicateurs(cheval):
    rangs = rangs_musique(cheval.get("musique", ""))
    if len(rangs) < 2:
        return None

    recents = rangs[:5]
    forme = sum(
        max(0, 11 - rang) / 10 for rang in recents
    ) / len(recents)
    regularite = sum(
        rang <= 5 for rang in rangs
    ) / len(rangs)

    return {
        "forme": round(forme, 6),
        "regularite": round(regularite, 6),
        "observations": len(rangs),
    }


def valider_course(course):
    if not isinstance(course, dict):
        raise ValueError("Course invalide")

    for cle in ("id", "hippodrome", "depart", "partants"):
        if not course.get(cle):
            raise ValueError("Champ absent : " + cle)

    if not verifier_source(course.get("source")):
        raise ValueError("Provenance HTTPS absente")

    depart = date_paris(course["depart"])
    chevaux = course["partants"]
    if not isinstance(chevaux, list):
        raise ValueError("Partants invalides")

    numeros = set()
    actifs = []
    for cheval in chevaux:
        if not isinstance(cheval, dict):
            raise ValueError("Cheval invalide")
        numero = cheval.get("numero")
        if type(numero) is not int or numero <= 0:
            raise ValueError("Numero invalide")
        if numero in numeros:
            raise ValueError("Numero duplique")
        numeros.add(numero)

        if cheval.get("non_partant") is True:
            continue
        if cheval.get("non_partant") is not False:
            raise ValueError("Statut partant inconnu")
        actifs.append(cheval)

    if len(actifs) < 5:
        raise ValueError("Moins de cinq partants")
    return depart, actifs


def analyser(course):
    depart, actifs = valider_course(course)
    instant = maintenant()

    if instant >= depart:
        raise ValueError("Course deja partie")

    profils = []
    for cheval in actifs:
        indic = indicateurs(cheval)
        if indic is None:
            raise ValueError(
                "Musique insuffisante pour le cheval "
                + str(cheval["numero"])
            )
        profils.append({
            "numero": cheval["numero"],
            "nom": cheval.get("nom", ""),
            **indic,
        })

    sorties = []
    for nom, (wf, wr) in POIDS.items():
        classement = []
        for profil in profils:
            score = (
                wf * profil["forme"]
                + wr * profil["regularite"]
            ) / (wf + wr)
            classement.append({
                "numero": profil["numero"],
                "score": round(score, 6),
            })

        classement.sort(
            key=lambda p: (-p["score"], p["numero"])
        )
        ordre = [p["numero"] for p in classement[:5]]
        ecart = (
            classement[0]["score"]
            - classement[1]["score"]
        )

        sorties.append({
            "moteur": nom,
            "gagnant_espere": ordre[0],
            "meilleur_place": ordre[1],
            "ordre_espere": ordre,
            "pari_retenu": None,
            "qualification": (
                "VERT" if ecart >= 0.05 else "JAUNE"
            ),
            "validation": "INDICATIF",
            "ecart_scores": round(ecart, 6),
            "scores": classement,
            "criteres": ["forme", "regularite"],
            "heure_paris": instant.isoformat(),
        })

    return {
        "logiciel": "X1000 PHOENIX",
        "course_id": course["id"],
        "hippodrome": course["hippodrome"],
        "nom": course.get("nom", ""),
        "depart": depart.isoformat(),
        "source": course["source"],
        "analyse_a": instant.isoformat(),
        "nombre_partants": len(actifs),
        "profils": profils,
        "moteurs": sorties,
        "statut": "ANALYSE_INDICATIVE",
        "avertissement": (
            "Scores heuristiques non calibres. "
            "Aucune garantie de resultat."
        ),
    }


def rapport_fige(document):
    if "rapport" in document:
        return document["rapport"]
    if "contenu" in document:
        return document["contenu"]["analyse"]
    raise ValueError("Format FIGE inconnu")


def verifier_fige(document):
    if not isinstance(document, dict):
        raise ValueError("FIGE invalide")
    if document.get("statut") != "FIGE_AVANT_DEPART":
        raise ValueError("Statut FIGE incorrect")

    if "contenu" in document:
        contenu = document["contenu"]
        if document.get("sha256") != empreinte(contenu):
            raise ValueError("Empreinte FIGE incorrecte")
        rapport = contenu["analyse"]
        instant = date_paris(contenu["fige_a"])
    else:
        contenu = {
            k: v for k, v in document.items()
            if k != "sha256"
        }
        if document.get("sha256") != empreinte(contenu):
            raise ValueError("Empreinte FIGE incorrecte")
        rapport = document["rapport"]
        instant = date_paris(document["fige_a"])

    depart = date_paris(rapport["depart"])
    analyse_a = date_paris(rapport["analyse_a"])
    if not analyse_a <= instant < depart:
        raise ValueError("Chronologie FIGE invalide")

    if not verifier_source(rapport.get("source")):
        raise ValueError("Source FIGE invalide")

    moteurs = rapport.get("moteurs", [])
    if sorted(m["moteur"] for m in moteurs) != sorted(MOTEURS):
        raise ValueError("Cinq moteurs requis")

    for moteur in moteurs:
        ordre = moteur.get(
            "ordre_espere", moteur.get("ordre", [])
        )
        if (
            len(ordre) < 5
            or len(set(ordre[:5])) != 5
            or moteur["gagnant_espere"] != ordre[0]
            or moteur["meilleur_place"] != ordre[1]
        ):
            raise ValueError("Selection incoherente")

    return True


def chemin_fige(course_id):
    return FIGES / (identifiant(course_id) + ".json")


def figer(rapport, marge=MARGE_MINUTES):
    chemin = chemin_fige(rapport["course_id"])

    if chemin.exists():
        document = lire(chemin)
        verifier_fige(document)
        return document

    instant = maintenant()
    depart = date_paris(rapport["depart"])
    secondes = (depart - instant).total_seconds()

    if not 0 < secondes <= marge * 60:
        return None

    if not verifier_source(rapport.get("source")):
        return None

    moteurs = rapport.get("moteurs", [])
    if sorted(m["moteur"] for m in moteurs) != sorted(MOTEURS):
        return None

    if not all(
        m.get("validation") == "INDICATIF"
        for m in moteurs
    ):
        return None

    document = {
        "statut": "FIGE_AVANT_DEPART",
        "fige_a": instant.isoformat(),
        "rapport": rapport,
    }
    document["sha256"] = empreinte(document)
    verifier_fige(document)

    FIGES.mkdir(parents=True, exist_ok=True)
    try:
        with chemin.open("x", encoding="utf-8") as fichier:
            json.dump(
                document, fichier,
                ensure_ascii=False, indent=2
            )
            fichier.write("\n")
    except FileExistsError:
        document = lire(chemin)
        verifier_fige(document)

    return document


def auditer(fige, arrivee):
    verifier_fige(fige)
    rapport = rapport_fige(fige)

    if arrivee.get("course_id") != rapport["course_id"]:
        raise ValueError("Course differente")
    if arrivee.get("statut") != "definitive":
        raise ValueError("Arrivee non definitive")
    if not verifier_source(arrivee.get("source")):
        raise ValueError("Source arrivee absente")

    ordre = arrivee.get("arrivee")
    if (
        not isinstance(ordre, list)
        or len(ordre) < 5
        or any(type(n) is not int or n <= 0 for n in ordre)
        or len(set(ordre)) != len(ordre)
    ):
        raise ValueError("Arrivee invalide")

    bilans = []
    for moteur in rapport["moteurs"]:
        choix = moteur.get(
            "ordre_espere", moteur.get("ordre", [])
        )[:5]
        bilans.append({
            "moteur": moteur["moteur"],
            "gagnant_espere": choix[0],
            "gagnant_trouve": choix[0] == ordre[0],
            "chevaux_dans_les_cinq": len(
                set(choix) & set(ordre[:5])
            ),
            "ordre_exact_cinq": choix == ordre[:5],
        })

    return {
        "logiciel": "X1000 PHOENIX",
        "course_id": rapport["course_id"],
        "statut": "AUDIT_EFFECTUE",
        "audit_a": maintenant().isoformat(),
        "fige_sha256": fige["sha256"],
        "source_arrivee": arrivee["source"],
        "arrivee_officielle": ordre,
        "moteurs": bilans,
    }


if __name__ == "__main__":
    print("X1000 PHOENIX M1-M5 : module disponible")
