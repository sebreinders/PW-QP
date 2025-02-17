import feedparser
import requests
from io import BytesIO
import PyPDF2
import re
from flask import Flask, request, render_template_string
import logging
import os

# Configuration du logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# URL du flux RSS et headers pour simuler un navigateur
RSS_URL = "https://www.parlement-wallonie.be/actu/rss_doc_generator.php"
headers = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/rss+xml, application/xml, text/xml"
}

# Récupération manuelle du flux RSS
logging.debug("Récupération du flux RSS...")
try:
    response = requests.get(RSS_URL, headers=headers, timeout=10)
    response.raise_for_status()
    rss_content = response.text
    logging.debug("Flux RSS récupéré (500 premiers caractères) : %s", rss_content[:500])
except Exception as e:
    logging.error("Erreur lors de la récupération du flux RSS: %s", e)
    rss_content = ""

# Parsing du flux RSS avec feedparser
feed = feedparser.parse(rss_content)
logging.debug("Nombre d'items dans le flux RSS après parsing : %d", len(feed.entries))

# Constitution d'une liste de publications avec leurs informations
# On ne télécharge PAS encore les PDF : le champ "text" est laissé vide pour l'instant.
publications = []
for entry in feed.entries:
    title = entry.get("title", "Sans titre")
    link = entry.get("link", "")
    pdf_urls = []

    # Vérifier la présence d'enclosures
    if 'enclosures' in entry:
        for enclosure in entry.enclosures:
            url = enclosure.get("href", "").strip()
            if url.lower().endswith('.pdf'):
                logging.debug("PDF détecté dans les enclosures : %s", url)
                pdf_urls.append(url)
    
    # Sinon, vérifier si le lien principal est un PDF
    if not pdf_urls and link.lower().strip().endswith('.pdf'):
        logging.debug("Le lien principal est identifié comme PDF : %s", link)
        pdf_urls.append(link)
    else:
        logging.debug("Aucun PDF détecté ou PDF déjà ajouté pour : %s", link)
    
    publications.append({
        "title": title,
        "link": link,
        "pdf_urls": pdf_urls,
        "text": ""  # Texte du PDF non encore extrait
    })

logging.debug("Nombre de publications chargées : %d", len(publications))


def extract_pdf_text(publication):
    """
    Fonction qui télécharge et extrait le texte des PDF pour une publication donnée.
    Elle retourne le texte extrait (concatené pour tous les PDF de la publication).
    """
    text_content = ""
    for pdf_url in publication["pdf_urls"]:
        try:
            logging.debug("Extraction du texte depuis le PDF : %s", pdf_url)
            # Téléchargement du PDF avec un header User-Agent
            pdf_response = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            pdf_response.raise_for_status()
            logging.debug("PDF téléchargé avec succès : %s - Taille : %d octets", pdf_url, len(pdf_response.content))
            pdf_file = BytesIO(pdf_response.content)
            reader = PyPDF2.PdfReader(pdf_file)
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                logging.debug("Page %d du PDF (%s) - %d caractères extraits", i, pdf_url, len(page_text))
                text_content += page_text + "\n"
        except Exception as e:
            logging.error("Erreur lors du traitement du PDF %s : %s", pdf_url, e)
    return text_content


# Création de l'application Flask
app = Flask(__name__)

# Template HTML pour le formulaire et l'affichage des résultats
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
    """Affiche le formulaire de recherche."""
    return render_template_string(HTML_TEMPLATE)

@app.route('/search', methods=['GET'])
def search():
    """
    Route de recherche :
    - Pour chaque publication, si le texte n'a pas encore été extrait, il est extrait ici.
    - Ensuite, on recherche les mots-clés dans le texte et on affiche un extrait contextuel.
    """
    query = request.args.get('query', '')
    if not query:
        return render_template_string(HTML_TEMPLATE, results=[])

    words = query.split()
    results = []
    context_chars = 50  # Nombre de caractères affichés autour de l'occurrence

    # Parcours de chaque publication
    for pub in publications:
        # Si le texte n'est pas encore extrait, on lance l'extraction
        if not pub["text"].strip() and pub["pdf_urls"]:
            logging.debug("Extraction lazy du texte pour la publication : %s", pub["title"])
            pub["text"] = extract_pdf_text(pub)
        text = pub["text"]
        occurrences = []
        for word in words:
            pattern = re.compile(r'(.{0,' + str(context_chars) + '})(' + re.escape(word) + r')(.{0,' + str(context_chars) + '})', re.IGNORECASE)
            for match in pattern.finditer(text):
                context = match.group(1) + match.group(2) + match.group(3)
                occurrences.append(context.strip())
        if occurrences:
            results.append({
                "title": pub["title"],
                "link": pub["link"],
                "occurrences": occurrences
            })
    
    return render_template_string(HTML_TEMPLATE, results=results)

if __name__ == '__main__':
    # Utilisation du port défini par la variable d'environnement PORT ou 5000 par défaut
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
