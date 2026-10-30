#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — audit consultatif M1–M5, lecture seule.

python autonomie_predictive_m1_m5.py --self-test
python autonomie_predictive_m1_m5.py
python autonomie_predictive_m1_m5.py --course 2026-10-30-R1-C1

Ne calcule aucun pronostic, ne valide ni ne crée aucun FIGÉ, n'écrit aucun fichier.
"""
import argparse
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path(__file__).resolve().parent / 'data'
PARIS = ZoneInfo('Europe/Paris')
MOTEURS = ('M1', 'M2', 'M3', 'M4', 'M5')
COURSE_FILES = ('publication_courses.json', 'collecte.json', 'courses_verifiees.json', 'courses.json', 'courses_pmu.json')
ANALYSIS_FILES = ('publication_analyses.json', 'publication_pronostics.json', 'analyses.json', 'pronostics.json')
FIELDS = ('musique', 'gains', 'age', 'sexe', 'jockey', 'driver', 'entraineur')
EXTRA = ('distance', 'terrain', 'corde', 'poids', 'numero_corde', 'historique_distance', 'historique_terrain', 'performances_detaillees', 'niveau_opposition')
ORIENTATIONS = {
    'M1': 'Forme, regularite, progression',
    'M2': 'Distance, terrain, parcours',
    'M3': 'Opposition, classe, scenario',
    'M4': 'Chevaux negliges, favoris fragiles',
    'M5': 'Analyse globale independante',
}


def present(v):
    return v is not None and v != '' and v != [] and v != {}


def first(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and present(d[k]):
            return d[k]
    return None


def number(v):
    if type(v) is int and v > 0:
        return v
    if isinstance(v, str) and re.fullmatch(r'0*[1-9][0-9]*', v.strip()):
        return int(v.strip())
    return None


def instant(v):
    if not isinstance(v, str):
        return None
    try:
        value = dt.datetime.fromisoformat(v.strip().replace('Z', '+00:00'))
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(PARIS)
    except (ValueError, OverflowError, TypeError):
        return None


def load_rows(names, keys):
    warnings = []
    for name in names:
        path = DATA / name
        if not path.is_file():
            continue
        try:
            with path.open('r', encoding='utf-8-sig') as f:
                raw = json.load(f)
            if isinstance(raw, list):
                if raw:
                    return raw, name, warnings
                warnings.append(f'{name}: liste vide')
                continue
            if isinstance(raw, dict):
                for block in (raw, raw.get('data')):
                    if isinstance(block, dict):
                        for key in keys:
                            rows = block.get(key)
                            if isinstance(rows, list):
                                if rows:
                                    return rows, name, warnings
                                warnings.append(f'{name}: {key} vide')
            warnings.append(f'{name}: aucune collection exploitable')
        except (OSError, ValueError, UnicodeError) as exc:
            warnings.append(f'{name}: {exc}')
    return [], None, warnings


def course_id(d):
    v = first(d, 'course_id', 'id', 'identifiant', 'id_course')
    return str(v).strip() if v is not None and not isinstance(v, bool) else ''


def france(c):
    v = c.get('localisation_france_verifiee')
    if v is True:
        return 'FRANCE_VERIFIEE'
    if v is False:
        return 'NON_FRANCE_OU_NON_VERIFIEE'
    pays = str(first(c, 'pays', 'country') or '').strip().upper()
    return 'FRANCE_DECLAREE_NON_VERIFIEE' if pays in ('FR', 'FRA', 'FRANCE') else 'LOCALISATION_NON_VERIFIEE'


def non_partant(p):
    status = str(first(p, 'statut', 'status') or '').strip().upper().replace('-', '_').replace(' ', '_')
    return p.get('non_partant') is True or p.get('nonPartant') is True or status in ('NP', 'NON_PARTANT', 'NONPARTANT', 'FORFAIT')


def sporting_audit(c):
    horses = first(c, 'partants', 'participants', 'chevaux')
    horses = horses if isinstance(horses, list) else []
    known, np_fiches, details, errors = set(), set(), [], []
    for h in horses:
        if not isinstance(h, dict):
            errors.append('Fiche cheval non objet')
            continue
        n = number(first(h, 'numero', 'numPmu', 'num', 'numeroPmu'))
        if n is None:
            errors.append('Numero de cheval invalide')
            continue
        if n in known:
            errors.append(f'Numero duplique : {n}')
            continue
        known.add(n)
        if non_partant(h):
            np_fiches.add(n)
        available = [k for k in FIELDS if present(h.get(k))]
        missing = [k for k in FIELDS if not present(h.get(k))]
        if present(h.get('jockey')) or present(h.get('driver')):
            missing = [k for k in missing if k not in ('jockey', 'driver')]
        else:
            missing = [k for k in missing if k not in ('jockey', 'driver')]
            missing.append('jockey_ou_driver')
        details.append({'numero': n, 'nom': first(h, 'nom', 'nomCheval'), 'non_partant_fiche': n in np_fiches,
                        'donnees_disponibles': available, 'donnees_manquantes': missing,
                        'donnees_complementaires': [k for k in EXTRA if present(h.get(k))],
                        'qualite': 'DONNEES_PARTIELLES' if missing else 'CHAMPS_DE_BASE_PRESENTS'})
    np_liste = set()
    raw_np = c.get('non_partants')
    if raw_np is not None and not isinstance(raw_np, list):
        errors.append('Liste non_partants invalide')
    elif isinstance(raw_np, list):
        for item in raw_np:
            v = first(item, 'numero', 'numPmu', 'num', 'numeroPmu') if isinstance(item, dict) else item
            n = number(v)
            if n is None:
                errors.append('Numero non-partant invalide')
            else:
                np_liste.add(n)
        if np_liste != np_fiches:
            errors.append('Desaccord liste non-partants / fiches chevaux')
    excluded = np_liste | np_fiches
    if excluded - known:
        errors.append('Non-partants absents des fiches chevaux')
    return {'chevaux': details, 'numeros_connus': sorted(known), 'non_partants': sorted(excluded),
            'erreurs': errors, 'nombre_fiches': len(details)}


def extract_engines(rows):
    collected = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = course_id(row)
        block = row.get('moteurs')
        if isinstance(block, list):
            entries = block
        elif isinstance(block, dict):
            entries = []
            for k, v in block.items():
                if isinstance(v, dict):
                    e = dict(v)
                    e.setdefault('moteur', k)
                    entries.append(e)
        else:
            entries = [row]
        for e in entries:
            if not isinstance(e, dict):
                continue
            eid = course_id(e) or cid
            engine = str(first(e, 'moteur', 'nom') or '').strip().upper()
            if eid and engine in MOTEURS:
                collected[eid][engine].append(e)
    groups, conflicts, repetitions = defaultdict(dict), defaultdict(list), defaultdict(list)
    for cid, engines in collected.items():
        for name, versions in engines.items():
            signatures = {json.dumps(v, sort_keys=True, ensure_ascii=False, default=str) for v in versions}
            if len(signatures) > 1:
                conflicts[cid].append(name)
            else:
                groups[cid][name] = versions[0]
                if len(versions) > 1:
                    repetitions[cid].append(name)
    return groups, conflicts, repetitions


def ordered_five(e):
    raw = first(e, 'ordre_espere', 'ordre_arrivee_espere', 'ordre')
    if not isinstance(raw, list):
        return None, 'Ordre non publie sous forme de liste'
    nums = [number(x) for x in raw]
    if len(nums) != 5:
        return None, 'Cinq positions requises'
    if None in nums or len(set(nums)) != 5:
        return None, 'Numero invalide ou repete'
    return nums, None


def time_audit(c, e):
    if c.get('depart_verifie') is not True:
        return 'DEPART_NON_VERIFIE'
    departure = instant(first(c, 'depart', 'heure_depart'))
    if departure is None:
        return 'DEPART_INVALIDE'
    computed = instant(first(e, 'analyse_a', 'horodatage', 'heure_analyse'))
    published = instant(first(e, 'publie_a', 'publication_a', 'date_publication'))
    if computed is not None and computed >= departure:
        return 'CALCUL_NON_ANTERIEUR_AU_DEPART'
    if published is not None and published >= departure:
        return 'PUBLICATION_NON_ANTERIEURE_AU_DEPART'
    if published is None:
        return 'PUBLICATION_AVANT_DEPART_NON_PROUVEE'
    if computed is None:
        return 'CALCUL_AVANT_DEPART_NON_PROUVE'
    if published < computed:
        return 'PUBLICATION_AVANT_CALCUL_INCOHERENTE'
    return 'CALCUL_ET_PUBLICATION_AVANT_DEPART'


def guidance(c, sport):
    result = ['Etudier tous les partants sans imposer les favoris',
              'Chercher les chevaux negliges et les favoris fragiles seulement avec des donnees verifiables',
              'Les accords entre moteurs ne sont pas des probabilites']
    if present(first(c, 'distance', 'distance_metres')):
        result.append('Etudier l aptitude documentee a la distance')
    if present(first(c, 'terrain', 'etat_terrain')):
        result.append('Etudier l aptitude documentee au terrain')
    if sport['non_partants']:
        result.append('Reexaminer les scenarios en tenant compte des non-partants')
    return result


def audit_course(cid, c, engines, conflicts, repetitions):
    sport = sporting_audit(c)
    known, excluded = set(sport['numeros_connus']), set(sport['non_partants'])
    result = {'course_id': cid, 'france': france(c), 'donnees_sportives': sport,
              'orientations_adaptatives': guidance(c, sport), 'moteurs': {},
              'accords_positions': {}, 'analyses_contradictoires': sorted(set(conflicts)),
              'repetitions_identiques': sorted(set(repetitions))}
    votes = defaultdict(list)
    for name in MOTEURS:
        if name in conflicts:
            result['moteurs'][name] = {'statut': 'AMBIGU', 'risques': ['Analyses contradictoires : aucune version choisie']}
            continue
        e = engines.get(name)
        if not isinstance(e, dict):
            result['moteurs'][name] = {'statut': 'ABSENT', 'risques': ['Aucune decision publiee']}
            continue
        order, issue = ordered_five(e)
        winner_raw, placed_raw = e.get('gagnant_espere'), e.get('meilleur_place')
        winner, placed = number(winner_raw), number(placed_raw)
        risks = list(sport['erreurs'])
        if issue:
            risks.append(issue)
        if winner is None:
            risks.append('Gagnant absent ou invalide')
        if placed is None:
            risks.append('Meilleur place absent ou invalide')
        if not known:
            risks.append('Partants non verifiables')
        if result['france'] != 'FRANCE_VERIFIEE':
            risks.append('Localisation francaise non confirmee')
        if order:
            for i, n in enumerate(order, 1):
                votes[i].append(n)
                if n in excluded:
                    risks.append(f'Position {i}: non-partant n°{n}')
                elif known and n not in known:
                    risks.append(f'Position {i}: numero inconnu n°{n}')
            if winner is not None and winner != order[0]:
                risks.append('Gagnant different de la position 1')
            if placed is not None and placed not in order:
                risks.append('Meilleur place absent des cinq positions')
        for label, n in (('Gagnant', winner), ('Place', placed)):
            if n is not None:
                if n in excluded:
                    risks.append(f'{label}: non-partant n°{n}')
                elif known and n not in known:
                    risks.append(f'{label}: numero inconnu n°{n}')
        timing = time_audit(c, e)
        if timing != 'CALCUL_ET_PUBLICATION_AVANT_DEPART':
            risks.append(timing)
        result['moteurs'][name] = {
            'orientation_libre': ORIENTATIONS[name], 'gagnant_publie_brut': winner_raw,
            'meilleur_place_publie_brut': placed_raw, 'ordre_publie_brut': first(e, 'ordre_espere', 'ordre_arrivee_espere', 'ordre'),
            'gagnant_numero_interpretable': winner, 'meilleur_place_numero_interpretable': placed,
            'ordre_numeros_interpretables': order, 'controle_horaire': timing,
            'risques': risks, 'statut': 'AUCUNE_ANOMALIE_DETECTEE' if not risks else 'A_CONTROLER',
            'validation_officielle_effectuee_par_ce_module': False, 'fige_produit_par_ce_module': False}
    for i in range(1, 6):
        result['accords_positions'][str(i)] = {'votes': dict(sorted(Counter(votes[i]).items())),
            'nature': 'Comparaison descriptive sans influence sur les choix'}
    return result


def self_test():
    assert number('07') == 7 and number(True) is None and number(0) is None
    assert ordered_five({'ordre_espere': [1, 2, 3, 4, 5]})[0] == [1, 2, 3, 4, 5]
    assert ordered_five({'ordre_espere': [1, 1, 3, 4, 5]})[0] is None
    course = {'id': 'TEST', 'localisation_france_verifiee': True, 'depart_verifie': True,
              'depart': '2026-10-30T15:00:00+01:00',
              'partants': [{'numero': i, 'nom': f'CHEVAL {i}', 'musique': '1p', 'driver': 'X'} for i in range(1, 7)],
              'non_partants': []}
    e = {'moteur': 'M1', 'gagnant_espere': 1, 'meilleur_place': 2,
         'ordre_espere': [1, 2, 3, 4, 5], 'analyse_a': '2026-10-30T14:00:00+01:00',
         'publie_a': '2026-10-30T14:01:00+01:00'}
    assert time_audit(course, e) == 'CALCUL_ET_PUBLICATION_AVANT_DEPART'
    assert time_audit(course, {**e, 'publie_a': '2026-10-30T16:00:00+01:00'}) == 'PUBLICATION_NON_ANTERIEURE_AU_DEPART'
    assert time_audit(course, {k: v for k, v in e.items() if k != 'publie_a'}) == 'PUBLICATION_AVANT_DEPART_NON_PROUVEE'
    assert not sporting_audit(course)['erreurs']
    assert sporting_audit({**course, 'non_partants': [2]})['erreurs']
    r = audit_course('TEST', course, {'M1': e}, [], [])
    assert r['moteurs']['M1']['ordre_numeros_interpretables'] == [1, 2, 3, 4, 5]
    assert r['moteurs']['M1']['gagnant_publie_brut'] == 1
    rows = [{'course_id': 'TEST', 'moteurs': [e, dict(e)]}]
    g, conflicts, repeats = extract_engines(rows)
    assert not conflicts['TEST'] and repeats['TEST'] == ['M1'] and 'M1' in g['TEST']
    rows[0]['moteurs'][1]['gagnant_espere'] = 3
    g, conflicts, repeats = extract_engines(rows)
    assert conflicts['TEST'] == ['M1'] and 'M1' not in g['TEST']
    print('SELF-TEST OK — lecture seule, controle consultatif')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--course', default=None)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    courses, cs, cw = load_rows(COURSE_FILES, ('courses', 'courses_verifiees'))
    analyses, ans, aw = load_rows(ANALYSIS_FILES, ('analyses', 'pronostics'))
    groups, conflicts, repeats = extract_engines(analyses)
    course_map, duplicate_courses = {}, set()
    for c in courses:
        cid = course_id(c)
        if not cid:
            continue
        if cid in course_map:
            duplicate_courses.add(cid)
        else:
            course_map[cid] = c
    ids = [args.course] if args.course else sorted(set(groups) | set(conflicts))
    report = {'systeme': 'X1000 PHOENIX', 'module': 'AUTONOMIE_PREDICTIVE_ADAPTATIVE',
              'version': '1.1-CONSULTATIF', 'date_paris': dt.datetime.now(PARIS).isoformat(),
              'lecture_seule': True, 'sources': {'courses': cs, 'analyses': ans},
              'avertissements_sources': cw + aw, 'courses': []}
    for cid in ids:
        if cid in duplicate_courses:
            report['courses'].append({'course_id': cid, 'statut': 'DOUBLON_COURSE', 'note': 'Aucune version selectionnee'})
        elif cid not in groups and cid not in conflicts:
            report['courses'].append({'course_id': cid, 'statut': 'ANALYSE_NON_DISPONIBLE'})
        elif cid not in course_map:
            report['courses'].append({'course_id': cid, 'statut': 'DONNEES_COURSE_ABSENTES'})
        else:
            report['courses'].append(audit_course(cid, course_map[cid], groups[cid], conflicts[cid], repeats[cid]))
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
