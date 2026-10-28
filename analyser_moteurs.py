#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — analyses heuristiques M1-M5, sans FIGÉ rétroactif."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'data' / 'publication_courses.json'
DEST = ROOT / 'data' / 'publication_analyses.json'


def musique(texte):
    # Supprime les années entre parenthèses, puis lit les performances récentes.
    texte = re.sub(r'\(\d{2,4}\)', '', str(texte or ''))
    return [(int(n), d.lower()) for n, d in re.findall(r'(\d+|[AaDdTtJj])([pPhHsSmMaA])', texte) if n.isdigit()][:10]


def scores(cheval):
    perf = musique(cheval.get('musique'))
    if not perf:
        return None
    rangs = [n for n, _ in perf]
    points = [max(0, 12 - min(n, 12)) / 11 for n in rangs]
    recents = points[:3]
    forme = sum(p * w for p, w in zip(recents, [0.5, 0.3, 0.2][:len(recents)])) / sum([0.5, 0.3, 0.2][:len(recents)])
    regularite = sum(n <= 3 for n in rangs) / len(rangs)
    victoires = sum(n == 1 for n in rangs) / len(rangs)
    constance = sum(points) / len(points)
    confiance = min(1, len(perf) / 5)
    return {
        'M1': .75 * forme + .25 * constance,
        'M2': .75 * regularite + .25 * constance,
        'M3': .65 * victoires + .35 * forme,
        'M4': .60 * regularite + .25 * constance + .15 * confiance,
        'M5': .30 * forme + .30 * regularite + .20 * victoires + .20 * confiance,
    }


def analyser(course, instant):
    depart = datetime.fromisoformat(course['depart'].replace('Z', '+00:00'))
    partants = [c for c in course.get('partants', []) if not c.get('non_partant') and c.get('statut') != 'NON_PARTANT']
    candidats = []
    for cheval in partants:
        valeurs = scores(cheval)
        if valeurs:
            candidats.append({'numero': cheval['numero'], 'nom': cheval.get('nom', ''), 'scores': valeurs})
    resultat = {
        'id': course.get('id'), 'hippodrome': course.get('hippodrome'),
        'depart': course['depart'], 'analyse_a': instant.isoformat(),
        'statut': 'ANALYSE_EXPLORATOIRE' if candidats else 'DONNEES_INSUFFISANTES',
        'fige': False, 'eligible_fige': instant < depart,
        'nombre_partants': len(partants), 'chevaux_evalues': len(candidats),
        'moteurs': {},
        'avertissement': 'Scores heuristiques fondés sur la musique disponible; ni probabilités calibrées ni conseil de pari.'
    }
    for moteur in ('M1', 'M2', 'M3', 'M4', 'M5'):
        ordre = sorted(candidats, key=lambda c: (-c['scores'][moteur], int(c['numero'])))
        resultat['moteurs'][moteur] = {
            'gagnant_espere': ordre[0]['numero'] if ordre else None,
            'meilleur_place': ordre[1]['numero'] if len(ordre) > 1 else None,
            'ordre_arrivee_espere': [c['numero'] for c in ordre[:5]],
            'classement_complet': [c['numero'] for c in ordre],
            'qualification': 'ETUDE_NON_VALIDEE',
            'pari_retenu': None,
            'validation': 'NON_FIGE',
        }
    return resultat


def main():
    if not SOURCE.is_file():
        raise SystemExit(f'Fichier PMU introuvable : {SOURCE}')
    donnees = json.loads(SOURCE.read_text(encoding='utf-8'))
    courses = donnees.get('courses')
    if not isinstance(courses, list):
        raise SystemExit('Format PMU incorrect : courses doit être une liste')
    instant = datetime.now(timezone.utc)
    analyses = []
    erreurs = []
    for course in courses:
        try:
            if not course.get('localisation_france_verifiee') or not course.get('depart_verifie'):
                continue
            analyses.append(analyser(course, instant))
        except (KeyError, TypeError, ValueError) as exc:
            erreurs.append({'id': course.get('id'), 'erreur': str(exc)})
    DEST.parent.mkdir(parents=True, exist_ok=True)
    payload = {'genere_a': instant.isoformat(), 'version': 'M1-M5-heuristique-1', 'analyses': analyses, 'erreurs': erreurs}
    tmp = DEST.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(DEST)
    print(f'{len(analyses)} courses analysées, {len(erreurs)} erreurs : {DEST}')

if __name__ == '__main__':
    main()
