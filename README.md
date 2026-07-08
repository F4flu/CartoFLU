# CartoFLU 🦊📡

**Application web de radiogoniométrie pour la recherche de balise**  
Développée par F4FLU / Christophe Chalandre /· ADRASEC 25 (Doubs)

---

## Présentation

CartoFLU est une application **HTML autonome** (un seul fichier) permettant de gérer une opération de radiogoniométrie en temps réel. Elle a été conçue pour les exercices et interventions de recherche de balise de détresse organisés par les ADRASEC.

Elle fonctionne directement dans le navigateur sans installation. Une simple connexion internet suffit pour charger les tuiles cartographiques (mode hors-ligne également disponible).

---

## Fonctionnalités principales

### 🗺️ Cartographie & Relevés
- Carte interactive basée sur **Leaflet.js**
- Saisie de relevés azimutaux par station
- Calcul et affichage des **intersections** des lignes de gisement
- Marqueurs de station personnalisés avec couleur unique par indicatif
- **Écoute négative** : marqueur dédié (oreille barrée) 
- Marqueur **BALISE** 

### 📋 Appel nominal (Roll Call)
- Gestion d'un tableau de stations actives
- **Watchdog timer** configurable par station avec alertes visuelles
- Gestion des départs et alertes de non-réponse
- Entrée **BALISE** représentant la position de la balise

### 📡 Intégration APRS
- Affichage des stations APRS sur la carte (via internet ou réseau radio)
- Indicatif + temps écoulé depuis la dernière trame
- Masquage individuel de stations avec liste triée des indicatifs cachés
  

### 💾 Sauvegarde 
- **Autosauvegarde** configurable (15 s / 30 s / 1 min / 5 min)
- Export/Import de sessions au format JSON
- Export/Import de sessions au format csv

### 🗂️ Gestion des indicatifs
- Autocomplétion native via `<datalist>` alimentée par un fichier `callsign_list.txt`
- Couleurs uniques automatiquement assignées à chaque indicatif

### 🌐 Mode hors-ligne
- Serveur de tuiles local via script Python 
  
---

## Utilisation

### Prérequis
- Navigateur moderne (Chrome ou Edge — recommandé)
- Connexion internet pour les tuiles en ligne (ou serveur local pour le mode hors-ligne)

### Démarrage rapide

1. **Télécharger** le zip de la dernière release et l'extraire dans le dossier de votre choix
2. **Ouvrir** le fichier CartoFLU-vxxx dans votre navigateur (double-clic ou glisser dans le navigateur)
3. *Optionnel* lancer le fichier "lancer_serveurs_python.bat" pour utiliser la connexion APRS et les fonds de cartes hors ligne

C'est tout. Aucune installation requise.

### Mode hors-ligne (tuiles locales)

Pour une utilisation sans internet (terrain, exercice isolé) :

1. Télécharger les tuiles OSM localement, avec Mobile Atlas Créator par exemple
2. Placer les tuiles dans un sous dossier nommé "tuiles", à coté du fichier "lancer_serveurs_python.bat"
3. Dans CartoFLU, sélectionner le fond de carte **"📴 Local (hors ligne)"**

### Fichier callsign_list.txt

Fichier texte simple, un indicatif par ligne :

```
F4FLU
F4XYZ
F5ABC
...
```

Un exemple de fichier est fourni dans le dépôt (`callsign_list.example.txt`).

---

## Structure du dépôt

```
CartoFLU/
├── python-portable               # Dossier python portable
├── tuiles                        # Dossier contenant les tuiles (mode hors ligne) avec un sous dossier par niveau de zoom
├── CartoFLU-vxxx.html            # Application principale (fichier unique)
├── callsign_list-example.txt     # Exemple de liste d'indicatifs
├── lancer_serveurs_python.bat    # Serveur de tuiles hors-ligne et APRS
├── cartoflu_serveur.py           # Script python pour le serveur
├── CartoFLU_Documentation_vxxx   # Documentation
└── README.md

```

---

## Captures d'écran

*(À venir — contributions bienvenues !)*

---

## Contribuer

Les contributions sont les bienvenues, que vous soyez radioamateur, développeur ou membre d'une ADRASEC !


### Signaler un bug ou proposer une idée

Utilisez l'onglet **[Issues](../../issues)** du dépôt GitHub. Merci de préciser :
- Votre navigateur et sa version
- Les étapes pour reproduire le problème
- Une capture d'écran si possible

### Idées de contributions

- Traductions (EN, DE...)
- Support d'autres formats d'import/export (GPX, KML...)
- Amélioration de l'algorithme d'intersection
- Intégration d'autres sources APRS
- Tests sur différents OS / navigateurs

---

## Dépendances

| Bibliothèque | Version | Rôle |
|---|---|---|
| [Leaflet.js](https://leafletjs.com/) | 1.9.x | Cartographie interactive |
| CartoDB Voyager | — | Fond de carte par défaut |

Toutes les dépendances sont chargées via CDN. Aucun `npm install` n'est nécessaire.

---

## Licence

Ce projet est distribué sous licence **GNU GPL v3**.  
Voir le fichier `LICENSE` ou [gnu.org/licenses/gpl-3.0](https://www.gnu.org/licenses/gpl-3.0.html).

---

## Contact

**F4FLU** — ADRASEC 25 (Doubs, Bourgogne-Franche-Comté)  
📧 f4flu@free.fr

---

*CartoFLU est un projet bénévole au service de la sécurité civile.*

Vous avez apprécié ? Payez moi un petit café :) https://buymeacoffee.com/f4flu   Merci !!!
