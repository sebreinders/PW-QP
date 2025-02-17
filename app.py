import feedparser
import requests
from io import BytesIO
import PyPDF2
import re
from flask import Flask, request, render_template_string
import logging
import os

# Configuration du logging pour afficher les messages de debug dans la console
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# URL du flux RSS
RSS_URL = "https://www.parlement-wallonie.be/actu/rss_doc_generator.php"

logging.debug("Début du parsing du flux RSS")
feed = feedparser.parse(RSS_URL)

# Liste qui contiendra les publications dont le texte des PDF a été extrait
publications = []

# Parcours de chaque item du flux RSS
for entry in feed.entries:
    # Affichage des clés disponibles pour vérifier la structure de l'item
    logging.debug("Clés disponibles dans l'item : %s", list(entry.keys()))
    
    title = entry.get("title", "Sans titre")
    link = entry.get("link", "")
    logging.debug("Traitement de l'item : %s - Lien principal : %s", title, link)
    
    pdf_urls = []
    
    # Vérification de la présence d'enclosures
    if 'enclosures' in entry:
        for enclosure in entry.enclosures:
            pdf_url = enclosure.get("href", "")
            if pdf_url.lower().endswith('.pdf'):
                logging.debug("PDF détecté dans les enclosures : %s", pdf_url)
                pdf_urls.append(pdf_url)
    
    # Si aucune enclosure ne correspond, on vérifie si le lien principal est un PDF
    if not pdf_urls and link.lower().endswith('.pdf'):
        logging.debug("Le lien principal est identifié comme PDF : %s", link)
        pdf_urls.append(link)
    else:
        logging.debug("Le lien principal n'est pas un PDF : %s", link)
    
    # Variable qui contiendra le texte extrait de tous les PDF de l'item
    text_content = ""
    
    # Parcours de chaque URL PDF détecté
    for pdf_url in pdf_urls:
        try:
            logging.debug("Tentative de téléchargement du PDF : %s", pdf_url)
            response = requests.get(pdf_url, timeout=10)
            response.raise_for_status()  # Lève une exception si le téléchargement échoue
            logging.debug("PDF téléchargé avec succès : %s - Taille : %d octets", pdf_url, len(response.content))
            
            pdf_file = BytesIO(response.content)
            
            # Extraction du texte avec PyPDF2
            reader = PyPDF2.PdfReader(pdf_file)
            pdf_text = ""
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                logging.debug("Page %d - Nombre de caractères extraits : %d", i, len(page_text))
                pdf_text += page_text + "\n"
            
            text_content += pdf_text
        except Exception as e:
            logging.error("Erreur lors du téléchargement ou du traitement du PDF %s : %s", pdf_url, e)
    
    # On ajoute la publication à la liste si du texte a été extrait
    if text_content.strip():
        logging.debug("Publication ajoutée : %s avec %d caractères extraits", title, len(text_content))
        publications.append({
            "title": title,
            "link": link,
            "pdf_urls": pdf_urls,
            "text": text_content
        })
    else:
        logging.debug("Aucun texte extrait pour la publication : %s", title)

logging.debug("Nombre de publications avec texte extrait : %d", len(publications))


# Création de l'application Flask
app = Flask(__name__)

# Template HTML intégrant le formulaire et l'affichage des résultats de recherche
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Recherche dans les publications PDF</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        input[type="text"] { width: 300px; padding: 5px; }
        button { padding: 5px 10px; }
        .result { margin-bottom: 20px; }
        .occurrence { font-style: italic; color: #555; }
    </style>
</head>
<body>
    <h1>Recherche dans les publications PDF</h1>
    <form method="GET" action="/search">
        <label for="query">Entrez le(s) mot(s) à rechercher :</label>
        <input type="text" id="query" name="query" required>
        <button type="submit">Rechercher</button>
    </form>
    {% if results %}
    <hr>
    <h2>Résultats de la recherche</h2>
    {% for res in results %}
        <div class="result">
            <h3>{{ res.title }}</h3>
            <p><a href="{{ res.link }}" target="_blank">Lien vers la publication</a></p>
            <ul>
                {% for occ in res.occurrences %}
                <li class="occurrence">...{{ occ }}...</li>
                {% endfor %}
            </ul>
        </div>
    {% endfor %}
    {% endif %}
</body>
</html>
'''

@app.route('/', methods=['GET'])
def index():
    """Page d'accueil affichant le formulaire de recherche."""
    return render_template_string(HTML_TEMPLATE)

@app.route('/search', methods=['GET'])
def search():
    """
    Route de recherche :
    - Récupère la requête de l'utilisateur.
    - Parcourt le texte extrait des PDF pour trouver les occurrences des mots recherchés.
    - Affiche un extrait contextuel pour chaque occurrence.
    """
    query = request.args.get('query', '')
    if not query:
        return render_template_string(HTML_TEMPLATE, results=[])
    
    words = query.split()
    results = []
    context_chars = 50  # Nombre de caractères à afficher autour du mot recherché
    
    # Parcours de chaque publication
    for pub in publications:
        text = pub['text']
        occurrences = []
        for word in words:
            pattern = re.compile(r'(.{0,' + str(context_chars) + '})(' + re.escape(word) + r')(.{0,' + str(context_chars) + '})', re.IGNORECASE)
            for match in pattern.finditer(text):
                context = match.group(1) + match.group(2) + match.group(3)
                occurrences.append(context.strip())
        if occurrences:
            results.append({
                "title": pub['title'],
                "link": pub['link'],
                "occurrences": occurrences
            })
    
    return render_template_string(HTML_TEMPLATE, results=results)

if __name__ == '__main__':
    # Utilisation du port défini par la variable d'environnement PORT (pour Render) ou 5000 par défaut
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
