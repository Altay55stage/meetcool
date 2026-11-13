# meet’cool ✳

[English](README.en.md) · [Dossier technique pour le professeur](docs/POUR_LE_PROF.md)

Une application pour trouver un lieu de rencontre à partir des départs de plusieurs personnes. L’accueil animé bleu cobalt et menthe conserve son introduction, son fond en relief, ses transformations au défilement, ses panneaux superposés et son manifeste. La partie application en bas de page propose trois étapes coulissantes — création, invitations, lieu — avec une grande carte à droite, dans la même palette.

## Lancer sur Mac

```sh
cd ~/Downloads/meetcool
./start-mac.command
```

Ou, avec Python 3.12 (version déclarée dans `pyproject.toml`) :

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload
```

Application : http://127.0.0.1:8000 — API : http://127.0.0.1:8000/docs.

## Carte et recherche mondiale

- Carte Leaflet et tuiles OpenStreetMap, sans clé de cartographie.
- Recherche explicite de villes et d’adresses avec Photon, basé sur OpenStreetMap.
- Départs et lieux candidats personnalisables dans n’importe quelle région couverte par les données.
- Matrice origine–destination et tracés routiers OSRM pour la voiture.
- Comparaison selon l’équité, le temps total ou l’arrivée au plus tôt.
- Couche de proximité : feux cartographiés, cafés, restaurants, bibliothèques et espaces collectifs.
- Algorithm Lab : Dijkstra, reconstruction de chemins, Floyd–Warshall et matrice OD.

Les scénarios prédéfinis servent à explorer l’outil. Les points générés dans ces scénarios ne sont pas des établissements vérifiés. Les données de proximité OpenStreetMap peuvent être incomplètes.

**Durées :** OSRM calcule sur le réseau routier, sans trafic en direct. En cas d’indisponibilité, et pour les modes vélo, marche ou transports non connectés à un moteur dédié, les durées sont des estimations géométriques et les segments sont indiqués comme tels. Les feux représentent leur présence cartographique ; leur couleur actuelle et leur durée ne sont pas connues. Aucun compte à rebours fictif n’est affiché.

Les services publics gratuits sont partagés et sans garantie de disponibilité. Pas de préchargement massif de tuiles, ni de recherche à chaque frappe. Les requêtes sont bornées et mises en cache côté serveur. Pour un usage important, les fournisseurs sont configurables : `GEOCODER_URL`, `OSRM_URL`, `OVERPASS_URL`.

## Réunions et invitations

1. L’organisateur crée une rencontre avec son nom et sa date, puis partage le lien d’invitation.
2. Chaque invité ouvre le lien, accepte et indique son départ : sa position actuelle sur clic explicite, ou la ville/adresse où il sera au moment du rendez-vous. La date de rencontre est affichée dans l’invitation.
3. L’organisateur consulte les réponses réelles et calcule le point commun. Aucun participant d’exemple n’est ajouté aux rencontres créées.

La géolocalisation reste volontaire, sans suivi continu. Les coordonnées des invités sont accessibles à l’organisateur via son lien privé et ne sont pas exposées aux autres invités. Les réponses sont fermées après confirmation ou annulation de la rencontre.

Les groupes n’ont pas de plafond fixe de participants dans l’interface ou les invitations. Les listes sont paginées dans le stockage partagé. Pour les grands groupes, le classement utilise des estimations géométriques ; les tracés routiers sont calculés dans une durée bornée, avec un repli explicitement indiqué pour les trajets restants. Les lieux générés autour du centre des départs sont indicatifs, pas des établissements vérifiés.

### Appwrite

Le déploiement utilise Appwrite via l’API REST serveur TablesDB. La base `meetcool` contient deux tables privées : `meetings` et `participants`. Les tables sont inaccessibles directement aux clients et le navigateur ne reçoit jamais la clé API.

Configuration serveur uniquement : `APPWRITE_ENDPOINT`, `APPWRITE_PROJECT_ID`, `APPWRITE_API_KEY`, `APPWRITE_DATABASE_ID` (par défaut `meetcool`). Voir `.env.example`. Le fichier local `.env.appwrite` est exclu du déploiement et du contrôle de version. Le lanceur Mac le charge automatiquement lorsqu’il existe.

Pour préparer un autre projet Appwrite autorisé, exporter ses variables puis lancer `python scripts/setup_appwrite.py`. Ce script crée seulement la base et les tables dédiées, leurs colonnes et l’index des participants ; il conserve les ressources déjà présentes.

### Autres stockages

Sans configuration partagée en local, SQLite assure la persistance. Supabase reste disponible comme alternative via `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` et `database/schema.sql`. Aucun projet Supabase existant n’a été modifié.

Sur Vercel, sans stockage partagé configuré, la création de rencontres est désactivée plutôt que d’utiliser un disque temporaire. Les clés restent dans les variables serveur de Vercel ; ne jamais les placer dans `static/` ou une URL.

## Déployer sur Vercel

Le projet utilise le runtime FastAPI, configuré dans `vercel.json`.

```sh
vercel link --project meetcool
vercel --prod
```

`.vercelignore` exclut l’environnement Python, la base locale, les fichiers `.env` et les états de travail. Aucune réunion locale n’est transférée lors du déploiement.

## Vérification

```sh
.venv/bin/python -m pytest -q
node --check static/app.js
node --check static/motion.js
.venv/bin/python -m compileall -q server.py geo.py storage.py engine.py
```

Les tests couvrent les algorithmes, les appels géographiques avec services simulés, la persistance, les permissions d’administration, la confidentialité des invités et l’absence de fausse persistance sur Vercel.

## Architecture

- `server.py` : FastAPI, réunions, validation et orchestration des calculs.
- `engine.py` : algorithmes pédagogiques et classement exact parmi les lieux fournis.
- `geo.py` : recherche Photon, matrice et routes OSRM, proximité Overpass.
- `storage.py` : Appwrite, Supabase ou SQLite local.
- `static/` : interface sans étape de compilation ni nouvelle bibliothèque d’animation.
- `scripts/setup_appwrite.py` : création du stockage Appwrite privé.
- `database/schema.sql` : alternative Supabase préparée, non appliquée.

L’optimalité concerne l’ensemble fini de lieux candidats et la matrice utilisée. Elle ne garantit pas un optimum sur tous les lieux du monde, ni une place disponible ou les horaires d’ouverture. Les comptes utilisateurs, les horaires de transports et le suivi temps réel restent des extensions. Les reçus et confirmations par e-mail sont implémentés via Appwrite Messaging.

Sources techniques : [politique des tuiles OSM](https://operations.osmfoundation.org/policies/tiles/), [Photon](https://github.com/komoot/photon), [OSRM](https://project-osrm.org/docs/v5.24.0/api/), [Supabase](https://supabase.com/docs/guides/api/securing-your-api), [FastAPI sur Vercel](https://vercel.com/docs/frameworks/backend/fastapi).

### E-mails et liens conservés

L’organisateur peut renseigner son e-mail à la création. Son reçu contient le lien privé d’administration et le lien public à partager. Le lien privé reste aussi disponible dans « Mes rencontres » sur le même navigateur et peut être copié à l’étape d’invitation. Chaque invité peut demander un reçu en renseignant son e-mail ; lors de la confirmation du lieu, l’organisateur et les invités concernés reçoivent individuellement le lieu et les liens Google Maps. La carte intégrée reste OpenStreetMap.

L’envoi passe exclusivement par Appwrite Messaging : il faut un fournisseur e-mail actif dans la console Appwrite et les droits `providers.read`, `messages.write`, `messages.read` pour la clé serveur. Sans fournisseur, aucun e-mail n’est envoyé et l’interface le signale ; la rencontre reste enregistrée. Les notifications sont identifiées pour éviter un double envoi lors d’une relance technique. `PUBLIC_APP_URL` fixe l’origine des liens envoyés (par défaut le domaine de production). Les e-mails et coordonnées ne sont pas exposés aux autres invités, et le lien privé n’est envoyé qu’au créateur.

### Parcours simplifié et vérification de l’interface

La rencontre suit trois étapes : créer, inviter, se retrouver. L’invitation peut être préparée dans WhatsApp, dans le client e-mail ou partagée par copie du lien. Le destinataire est choisi dans l’application de partage ; ouvrir ces liens n’envoie aucun message automatiquement. Seul le lien public est partagé. L’accès privé organisateur est replié dans « Retrouver ma rencontre ».

« Comment ça marche ? » explique la comparaison exhaustive des points candidats, les trois objectifs et les limites des durées. Les démonstrations Dijkstra et Floyd–Warshall restent accessibles dans une section pédagogique distincte.

Le test navigateur utilise Playwright déjà installé dans l’espace d’outils séparé, sans ajouter de dépendance à l’application. Démarrer le serveur local sur le port 8011, puis exécuter :

```bash
MEETCOOL_TOOLKIT_PACKAGE="$HOME/Developer/codex-toolkit/js/package.json" node scripts/check_planner.mjs
```

Les appels de création, d’acceptation et de confirmation sont simulés : le test n’envoie aucun e-mail et ne crée aucune rencontre réelle.

### Dossier pour le cours

Le [dossier technique](docs/POUR_LE_PROF.md) détaille les technologies, la circulation des données, les formules et les complexités, les démonstrations Dijkstra/Floyd–Warshall, les limites et la procédure de publication sur Vercel. Le projet a été développé avec une assistance Codex ; cette aide est déclarée dans le dossier. Une [présentation en anglais](README.en.md) est également disponible.
