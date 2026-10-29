#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X1000 PHOENIX - PUBLICATION UNIFIEE M1-M5
Version 9.0

Compatible :
- pmu_engine.py
- analyser_moteurs.py
- phoenix.py
- GitHub Actions
- GitHub Pages

Fonctions :
- Controle de la collecte PMU
- Fraicheur maximale de 20 minutes
- Verification avant depart
- Analyse heuristique M1-M5
- Publication du tableau officiel
- Publication des PV d'analyse
- Conservation des FIGES historiques
- Verification SHA256 des FIGES
- Publication des audits controles
- Diagnostic des erreurs
- Ecriture JSON atomique

Securite :
- Aucune arrivee inventee
- Aucun pronostic retroactif
- Aucun nouveau FIGE automatique
- Aucun FIGE historique ecrase
- Aucune validation de pari fictive

Execution :
    python publication.py

Tests sans reseau :
    python publication.py --self-test
"""

import argparse
import datetime as dt
import hashlib
import json
import re
import sys

from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from phoenix import (
    DATA,
    FIGES,
    lire,
    ecrire,
    verifier_fige,
    controle_fige,
    rapport_fige,
)

from analyser_moteurs import analyser as analyser_moteurs


# ==========================================
# CONFIGURATION
# ==========================================

VERSION = "PUBLICATION-UNIFIEE-9.0"

PARIS = ZoneInfo("Europe/Paris")

MOTEURS = (
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
)

MAX_AGE_MINUTES = 20

SOURCE = DATA / "collecte.json"


# ==========================================
# HORLOGE
# ==========================================

def maintenant():
    return dt.datetime.now(PARIS)


def date_heure(valeur):
    if not isinstance(valeur, str):
        raise ValueError("Horodatage absent")

    instant = dt.datetime.fromisoformat(
        valeur.replace("Z", "+00:00")
    )

    if (
        instant.tzinfo is None
        or instant.utcoffset() is None
    ):
        raise ValueError("Fuseau horaire absent")

    return instant.astimezone(PARIS)


# ==========================================
# VALIDATION URL
# ==========================================

def url_https(valeur):
    if not isinstance(valeur, str):
        return False

    try:
        url = urlparse(valeur)

        return (
            url.scheme == "https"
            and bool(url.hostname)
            and not url.username
            and not url.password
        )

    except (TypeError, ValueError):
        return False


# ==========================================
# VALIDATION DES NUMEROS
# ==========================================

def numero(valeur):
    if type(valeur) is int and valeur > 0:
        return valeur

    if isinstance(valeur, str):
        valeur = valeur.strip()

        if re.fullmatch(r"[1-9]\d*", valeur):
            return int(valeur)

    raise ValueError("Numero invalide")


def est_non_partant(cheval):
    statut = str(
        cheval.get("statut") or ""
    ).strip().upper()

    statut = statut.replace(
        "-", "_"
    ).replace(
        " ", "_"
    )

    return (
        cheval.get("non_partant") is True
        or statut in (
            "NON_PARTANT",
            "NONPARTANT",
            "NP",
            "FORFAIT",
        )
    )


# ==========================================
# CONTROLE AVANT DEPART
# ==========================================

def controle_avant_depart(course, instant):
    raisons = []

    if not isinstance(course, dict):
        return ["Course invalide"]

    if (
        course.get(
            "localisation_france_verifiee"
        ) is not True
    ):
        raisons.append(
            "Localisation France non confirmee"
        )

    if course.get("depart_verifie") is not True:
        raisons.append(
            "Horaire de depart non confirme"
        )

    try:
        depart = date_heure(
            course.get("depart")
        )

        if instant >= depart:
            raisons.append(
                "Depart atteint ou depasse"
            )

    except (
        ValueError,
        TypeError,
        OverflowError,
    ):
        raisons.append(
            "Horaire de depart invalide"
        )

    try:
        collecte_a = date_heure(
            course.get("collecte_a")
        )

        age = (
            instant - collecte_a
        ).total_seconds()

        if age < -60:
            raisons.append(
                "Collecte datee du futur"
            )

        elif age > MAX_AGE_MINUTES * 60:
            raisons.append(
                "Collecte trop ancienne"
            )

    except (
        ValueError,
        TypeError,
        OverflowError,
    ):
        raisons.append(
            "Horodatage collecte invalide"
        )

    source = course.get("source")

    if not url_https(source):
        raisons.append(
            "Source HTTPS invalide"
        )

    preuve = course.get("controle_source")

    if not isinstance(preuve, dict):
        raisons.append(
            "Tracabilite API absente"
        )

    else:
        if (
            preuve.get("mode")
            != "API_REPONSE_DIRECTE"
        ):
            raisons.append(
                "Mode de collecte non confirme"
            )

        if (
            preuve.get("structure_validee")
            is not True
        ):
            raisons.append(
                "Structure API non validee"
            )

        if (
            not url_https(
                preuve.get("participants_url")
            )
            or preuve.get("participants_url")
            != source
        ):
            raisons.append(
                "URL participants incoherente"
            )

    partants = course.get("partants")

    if not isinstance(partants, list) or not partants:
        raisons.append(
            "Liste des partants absente"
        )

        return raisons

    numeros = set()
    actifs = []
    non_partants = []

    for cheval in partants:
        if not isinstance(cheval, dict):
            raisons.append(
                "Fiche cheval invalide"
            )
            continue

        try:
            n = numero(
                cheval.get("numero")
            )

        except ValueError:
            raisons.append(
                "Numero de cheval invalide"
            )
            continue

        if n in numeros:
            raisons.append(
                f"Numero duplique : {n}"
            )
            continue

        numeros.add(n)

        if not str(
            cheval.get("nom") or ""
        ).strip():
            raisons.append(
                f"Nom absent pour numero {n}"
            )

        if est_non_partant(cheval):
            non_partants.append(n)

        else:
            actifs.append(n)

    if len(actifs) < 2:
        raisons.append(
            "Moins de deux partants actifs"
        )

    if (
        course.get("nombre_partants")
        != len(actifs)
    ):
        raisons.append(
            "Nombre de partants incoherent"
        )

    try:
        np_source = [
            numero(n)
            for n in course.get(
                "non_partants", []
            )
        ]

        if sorted(np_source) != sorted(non_partants):
            raisons.append(
                "Liste des non-partants incoherente"
            )

    except (ValueError, TypeError):
        raisons.append(
            "Numeros des non-partants invalides"
        )

    return raisons


# ==========================================
# LECTURE DES COLLECTIONS
# ==========================================

def collection(nom, cle, erreurs):
    chemin = DATA / f"{nom}.json"

    if not chemin.is_file():
        return []

    try:
        objet = lire(chemin)

        if isinstance(objet, list):
            lignes = objet

        elif isinstance(objet, dict):
            lignes = objet.get(cle)

        else:
            lignes = None

        if not isinstance(lignes, list):
            raise ValueError(
                "Collection JSON invalide"
            )

        return lignes

    except (
        OSError,
        ValueError,
        TypeError,
    ) as erreur:
        erreurs.append(
            f"{chemin.name}: {erreur}"
        )

        return []


# ==========================================
# ARCHIVES HISTORIQUES
# ==========================================

def archives(dossier, erreurs, figes=False):
    resultat = []

    racine = DATA / dossier

    if not racine.exists():
        return resultat

    for chemin in sorted(
        racine.glob("*.json")
    ):
        try:
            document = lire(chemin)

            if not isinstance(document, dict):
                raise ValueError(
                    "Archive JSON invalide"
                )

            if figes:
                verifier_fige(document)

            resultat.append(document)

        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ) as erreur:
            erreurs.append(
                f"Archive {chemin.name}: {erreur}"
            )

    return resultat


# ==========================================
# DEDOUBLONNAGE
# ==========================================

def uniques(documents, cle):
    resultat = []
    vus = set()

    for document in documents:
        if not isinstance(document, dict):
            continue

        valeur = document.get(cle)

        if (
            not isinstance(valeur, (str, int))
            or isinstance(valeur, bool)
        ):
            continue

        identifiant = str(valeur)

        if identifiant in vus:
            continue

        vus.add(identifiant)
        resultat.append(document)

    return resultat


# ==========================================
# CHARGEMENT DES FIGES
# ==========================================

def charger_figes(erreurs):
    candidats = (
        archives(
            "figes",
            erreurs,
            figes=True
        )
        + collection(
            "figes",
            "figes",
            erreurs
        )
    )

    resultat = []
    vus = set()

    for document in candidats:
        try:
            verifier_fige(document)

            rapport = rapport_fige(document)

            cid = str(
                rapport["course_id"]
            )

            sha = document.get("sha256")

            if not isinstance(sha, str):
                raise ValueError(
                    "SHA256 absent"
                )

            cle = (
                cid,
                sha.lower()
            )

            if cle in vus:
                continue

            vus.add(cle)

            copie = dict(document)

            copie["verification_publication"] = (
                controle_fige(document)[
                    "integrite"
                ]
            )

            resultat.append(copie)

        except (
            ValueError,
            TypeError,
            KeyError,
        ) as erreur:
            erreurs.append(
                f"FIGE historique: {erreur}"
            )

    return resultat


# ==========================================
# CHARGEMENT DES AUDITS
# ==========================================

def charger_audits(erreurs, figes):
    empreintes = {
        f["sha256"].lower()
        for f in figes
        if isinstance(
            f.get("sha256"),
            str
        )
    }

    candidats = (
        archives("audits", erreurs)
        + collection(
            "audits",
            "audits",
            erreurs
        )
    )

    resultat = []
    vus = set()

    for audit in candidats:
        if not isinstance(audit, dict):
            erreurs.append(
                "Audit non objet"
            )
            continue

        sha = audit.get(
            "fige_sha256"
        )

        arrivee = audit.get(
            "arrivee_officielle"
        )

        source = (
            audit.get("source_arrivee")
            or audit.get("source_resultat")
        )

        valide = (
            isinstance(sha, str)
            and sha.lower() in empreintes
            and audit.get("statut")
            == "AUDIT_EFFECTUE"
            and url_https(source)
            and isinstance(arrivee, list)
            and len(arrivee) >= 5
            and all(
                type(n) is int and n > 0
                for n in arrivee
            )
            and len(set(arrivee))
            == len(arrivee)
        )

        if not valide:
            erreurs.append(
                "Audit non verifiable: "
                + str(
                    audit.get(
                        "course_id", "?"
                    )
                )
            )
            continue

        cle = (
            str(audit.get("course_id")),
            sha.lower(),
            tuple(arrivee)
        )

        if cle in vus:
            continue

        vus.add(cle)

        copie = dict(audit)

        copie["verification_publication"] = (
            "STRUCTURE_VALIDE_"
            "SOURCE_NON_REVERIFIEE"
        )

        resultat.append(copie)

    return resultat


# ==========================================
# NORMALISATION M1-M5
# ==========================================

def normaliser_moteurs(analyse):
    bloc = analyse.get(
        "moteurs", []
    )

    if isinstance(bloc, dict):
        bloc = [
            {
                **valeur,
                "moteur": nom
            }
            for nom, valeur in bloc.items()
            if isinstance(valeur, dict)
        ]

    if not isinstance(bloc, list):
        return []

    resultat = []
    vus = set()

    for moteur in bloc:
        if not isinstance(moteur, dict):
            continue

        nom = moteur.get("moteur")

        if nom not in MOTEURS or nom in vus:
            continue

        vus.add(nom)

        ordre = (
            moteur.get("ordre_espere")
            or moteur.get(
                "ordre_arrivee_espere"
            )
            or []
        )

        if not isinstance(ordre, list):
            continue

        try:
            numeros = [
                numero(n)
                for n in ordre
            ]

        except ValueError:
            continue

        if len(numeros) != len(set(numeros)):
            continue

        top = numeros[:5]

        resultat.append({
            "moteur": nom,
            "gagnant_espere": (
                top[0] if top else None
            ),
            "meilleur_place": (
                top[1]
                if len(top) > 1
                else None
            ),
            "ordre_espere": top,
            "ordre_arrivee_espere": top,
            "classement_complet": numeros,
            "qualification": "ETUDE_NON_VALIDEE",
            "validation": "NON_FIGE",
            "pari_retenu": None,
            "fige": False,
            "methode": "HEURISTIQUE_MUSIQUE"
        })

    return resultat


# ==========================================
# COLLECTE DU JOUR
# ==========================================

def collecte_du_jour(erreurs, instant=None):
    instant = instant or maintenant()

    if not SOURCE.is_file():
        erreurs.append(
            "Collecte PMU absente"
        )
        return {}, []

    try:
        collecte = lire(SOURCE)

        if not isinstance(collecte, dict):
            raise ValueError(
                "Collecte non objet"
            )

        if (
            collecte.get("date")
            != instant.date().isoformat()
        ):
            raise ValueError(
                "Collecte d'une autre date"
            )

        if collecte.get("statut") not in (
            "OK",
            "PARTIEL",
            "AUCUNE_COURSE"
        ):
            raise ValueError(
                "Statut collecte invalide"
            )

        courses = collecte.get("courses")

        if not isinstance(courses, list):
            raise ValueError(
                "Liste des courses absente"
            )

        erreurs_source = collecte.get(
            "erreurs", []
        )

        if isinstance(erreurs_source, list):
            erreurs.extend(
                str(e)
                for e in erreurs_source
            )

        return collecte, courses

    except (
        OSError,
        ValueError,
        TypeError,
    ) as erreur:
        erreurs.append(
            f"Collecte inexploitable: {erreur}"
        )

        return {}, []


# ==========================================
# EMPREINTES DES ARCHIVES
# ==========================================

def empreintes_archives():
    resultat = {}

    for dossier in (
        "figes",
        "pv",
        "audits",
        "journaux"
    ):
        racine = DATA / dossier

        if not racine.exists():
            continue

        for chemin in sorted(
            racine.rglob("*")
        ):
            if not chemin.is_file():
                continue

            relatif = str(
                chemin.relative_to(DATA)
            )

            resultat[relatif] = hashlib.sha256(
                chemin.read_bytes()
            ).hexdigest()

    return resultat


# ==========================================
# CONSTRUCTION DES PV
# ==========================================

def creer_pv(course, analyse, instant):
    cid = str(
        course["id"]
    )

    identifiant = (
        "ANALYSE-"
        + cid
        + "-"
        + instant.strftime(
            "%Y%m%dT%H%M%S%f"
        )
    )

    return {
        "pv_id": identifiant,
        "course_id": cid,
        "type": "PV_ANALYSE",
        "statut": "PV_ANALYSE_NON_FIGE",
        "cree_a": instant.isoformat(),
        "depart": course.get("depart"),
        "source": course.get("source"),
        "moteurs": analyse.get(
            "moteurs", []
        ),
        "fige": False,
        "avertissement": (
            "Analyse indicative non validee. "
            "Ce PV ne constitue pas un FIGE."
        )
    }


# ==========================================
# PUBLICATION PRINCIPALE
# ==========================================

def publier():
    DATA.mkdir(
        parents=True,
        exist_ok=True
    )

    FIGES.mkdir(
        parents=True,
        exist_ok=True
    )

    avant = empreintes_archives()

    instant = maintenant()

    erreurs = []

    collecte, brutes = collecte_du_jour(
        erreurs,
        instant
    )

    courses = []
    pronostics = []
    pv_nouveaux = []

    for course in brutes:
        if not isinstance(course, dict):
            erreurs.append(
                "Course non objet"
            )
            continue

        cid = (
            course.get("id")
            or course.get("course_id")
        )

        if cid is None or not str(cid).strip():
            erreurs.append(
                "Course sans identifiant"
            )
            continue

        cid = str(cid)

        ligne = dict(course)

        ligne["id"] = cid
        ligne["course_id"] = cid
        ligne["moteurs"] = []
        ligne["statut"] = "CONTROLE_NON_SATISFAIT"

        raisons = controle_avant_depart(
            course,
            instant
        )

        if not raisons:
            try:
                analyse = analyser_moteurs(
                    course,
                    instant
                )

                moteurs = normaliser_moteurs(
                    analyse
                )

                ligne["moteurs"] = moteurs

                ligne["analyse_a"] = (
                    analyse.get("analyse_a")
                )

                if (
                    analyse.get("chevaux_evalues", 0)
                    >= 2
                    and any(
                        m["ordre_espere"]
                        for m in moteurs
                    )
                ):
                    ligne["statut"] = (
                        "ANALYSE_INDICATIVE"
                    )

                    pv_nouveaux.append(
                        creer_pv(
                            course,
                            {
                                **analyse,
                                "moteurs": moteurs
                            },
                            instant
                        )
                    )

                else:
                    ligne["statut"] = (
                        "DONNEES_INSUFFISANTES"
                    )

            except (
                ValueError,
                TypeError,
                KeyError,
                OverflowError,
            ) as erreur:
                raisons.append(
                    f"Analyse impossible: {erreur}"
                )

                ligne["statut"] = (
                    "ERREUR_ANALYSE"
                )

        if raisons:
            ligne["difficultes"] = raisons

        courses.append(ligne)

        for moteur in ligne["moteurs"]:
            pronostics.append({
                **moteur,
                "course_id": cid,
                "hippodrome": course.get(
                    "hippodrome"
                ),
                "depart": course.get("depart"),
                "statut_course": ligne["statut"],
            })

    # ======================================
    # FIGES HISTORIQUES
    # ======================================

    figes = charger_figes(erreurs)

    index = {
        str(c["id"]): c
        for c in courses
    }

    for document in figes:
        try:
            rapport_fig = rapport_fige(
                document
            )

            cid = str(
                rapport_fig["course_id"]
            )

            integrite = controle_fige(
                document
            )["integrite"]

            if cid not in index:
                ligne = {
                    "id": cid,
                    "course_id": cid,
                    "hippodrome": rapport_fig.get(
                        "hippodrome"
                    ),
                    "depart": rapport_fig.get(
                        "depart"
                    ),
                    "source": rapport_fig.get(
                        "source"
                    ),
                    "moteurs": [],
                    "statut": "FIGE_HISTORIQUE"
                }

                courses.append(ligne)
                index[cid] = ligne

            index[cid].setdefault(
                "figes_historiques", []
            ).append({
                "sha256": document.get(
                    "sha256"
                ),
                "integrite": integrite,
                "fige_a": rapport_fig.get(
                    "fige_a"
                ),
                "moteurs": rapport_fig.get(
                    "moteurs", []
                )
            })

        except (
            ValueError,
            TypeError,
            KeyError,
        ) as erreur:
            erreurs.append(
                f"FIGE historique: {erreur}"
            )

    # ======================================
    # AUDITS ET PV
    # ======================================

    audits = charger_audits(
        erreurs,
        figes
    )

    pv = uniques(
        archives("pv", erreurs)
        + collection(
            "pv",
            "pv",
            erreurs
        )
        + pv_nouveaux,
        "pv_id"
    )

    analyses_count = sum(
        c.get("statut")
        == "ANALYSE_INDICATIVE"
        for c in courses
    )

    # ======================================
    # RAPPORT
    # ======================================

    if erreurs:
        statut = "PUBLICATION_PARTIELLE"

    elif analyses_count:
        statut = "ANALYSES_DISPONIBLES"

    elif figes:
        statut = "ARCHIVES_DISPONIBLES"

    else:
        statut = "AUCUNE_ANALYSE"

    rapport = {
        "logiciel": "X1000 PHOENIX",
        "version": VERSION,
        "generated_at_paris": (
            maintenant().isoformat()
        ),
        "source_donnees": collecte.get(
            "source"
        ),
        "moteurs_actifs": list(MOTEURS),
        "courses_collectees": len(brutes),
        "courses_count": len(courses),
        "analyses_count": analyses_count,
        "pronostics_count": len(pronostics),
        "pv_count": len(pv),
        "figes_count": len(figes),
        "audits_count": len(audits),
        "nouveaux_figes": 0,
        "status": statut,
        "difficultes": [
            {
                "moteur": "SYSTEME",
                "difficulte": erreur
            }
            for erreur in erreurs
        ],
        "avertissement": (
            "Analyses heuristiques non calibrees. "
            "Aucun nouveau FIGE automatique. "
            "Aucun resultat officiel invente. "
            "Sources externes non reverifiees "
            "independamment par publication.py."
        )
    }

    # ======================================
    # PROTECTION HISTORIQUE
    # ======================================

    if empreintes_archives() != avant:
        raise RuntimeError(
            "Archives modifiees pendant la lecture"
        )

    # ======================================
    # PUBLICATIONS JSON
    # ======================================

    publications = (
        ("courses", courses),
        ("pronostics", pronostics),
        ("pv", pv),
        ("figes", figes),
        ("audits", audits),
    )

    for nom, objets in publications:
        ecrire(
            DATA / f"publication_{nom}.json",
            {nom: objets}
        )

    ecrire(
        DATA / "publication_rapport.json",
        rapport
    )

    ecrire(
        DATA / "rapport_actions.json",
        rapport
    )

    # ======================================
    # CONTROLE FINAL
    # ======================================

    if empreintes_archives() != avant:
        raise RuntimeError(
            "Archives historiques modifiees"
        )

    print(
        json.dumps(
            rapport,
            ensure_ascii=False,
            indent=2
        )
    )

    return rapport


# ==========================================
# TESTS SANS RESEAU
# ==========================================

def self_test():
    assert url_https(
        "https://example.org/test"
    )

    assert not url_https(
        "http://example.org/test"
    )

    assert numero(4) == 4
    assert numero("12") == 12

    assert est_non_partant({
        "statut": "NON_PARTANT"
    })

    instant = date_heure(
        "2026-10-29T12:00:00+01:00"
    )

    course = {
        "id": "2026-10-29-R1-C1",
        "depart": (
            "2026-10-29T15:00:00+01:00"
        ),
        "depart_verifie": True,
        "localisation_france_verifiee": True,
        "collecte_a": (
            "2026-10-29T11:55:00+01:00"
        ),
        "source": (
            "https://example.org/participants"
        ),
        "controle_source": {
            "mode": "API_REPONSE_DIRECTE",
            "structure_validee": True,
            "participants_url": (
                "https://example.org/participants"
            )
        },
        "nombre_partants": 2,
        "non_partants": [3],
        "partants": [
            {
                "numero": 1,
                "nom": "TEST 1",
                "non_partant": False
            },
            {
                "numero": 2,
                "nom": "TEST 2",
                "non_partant": False
            },
            {
                "numero": 3,
                "nom": "TEST 3",
                "non_partant": True
            }
        ]
    }

    assert controle_avant_depart(
        course,
        instant
    ) == []

    assert len(
        normaliser_moteurs({
            "moteurs": [
                {
                    "moteur": "M1",
                    "ordre_espere": [1, 2, 3]
                }
            ]
        })
    ) == 1

    print(
        "X1000 PHOENIX 9.0 : "
        "tests locaux OK"
    )


# ==========================================
# EXECUTION
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "X1000 PHOENIX - "
            "Publication M1-M5"
        )
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Tests sans reseau"
    )

    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    try:
        publier()
        return 0

    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
    ) as erreur:
        print(
            f"ERREUR PUBLICATION : {erreur}",
            file=sys.stderr
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())
