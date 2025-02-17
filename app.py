import feedparser
import requests
from io import BytesIO
import PyPDF2
import re
from flask import Flask, request, render_template_string

# URL du flux RSS à analyser
RSS_URL = "https://www.parlement-wallonie.be/actu/rss_doc_generator.php"

# Analyse du flux RSS
feed = feedparser.parse(RSS_URL)

# Liste qui contiendra les publications dont on a pu extraire le contenu PDF
# Chaque élément est un dictionnaire contenant : titre, lien, liste des URLs PDF et le texte extrait
publications = []

# Parcours de chaque entrée du flux RSS
for entry in feed.entries:
    title = entry.get("title", "Sans titre")
    link = entry.get("link", "")
    pdf_urls = []
    
    # Vérification de la présence d'enclosures dans l'entrée
    if 'enclosures' in entry:
        for enclosure in entry.enclosures:
            pdf_url = enclosure.get("href", "")
            # On considère que le lien correspond à un PDF si son URL se termine par .pdf
            if pdf_url.lower().endswith('.pdf'):
                pdf_urls.append(pdf_url)
    
    # Parfois, le lien principal de l'entrée peut pointer directement vers un PDF
    if not pdf_urls and link.lower().endswith('.pdf'):
        pdf_urls.append(link)
    
    # Variable qui contiendra le texte extrait de tous les PDF de cette publication
    text_content = ""
    
    # Pour chaque URL PDF trouvée, on tente de télécharger et d'extraire le texte
    for pdf_url in pdf_urls:
        try:
            print(f"Téléchargement du PDF : {pdf_url}")
            response = requests.get(pdf_url)
            response.raise_for_status()  # Pour lever une exception en cas d'erreur HTTP
            pdf_file = BytesIO(response.content)
            
            # Utilisation de PyPDF2 pour lire le PDF
            reader = PyPDF2.PdfReader(pdf_file)
            pdf_text = ""
            for page in reader.pages:
                page_text = page.extract_text() or ""
                pdf_text += page_text + "\n"
            
            text_content += pdf_text
        except Exception as e:
            print(f"Erreur lors du traitement du PDF {pdf_url} : {e}")
    
    # On conserve la publication uniquement si du texte a pu être extrait
    if text_content.strip():
        publications.append({
            "title": title,
            "link": link,
            "pdf_urls": pdf_urls,
            "text": text_content
        })

print(f"Nombre de publications avec texte extrait : {len(publications)}")

# Création de l'application Flask
app = Flask(__name__)

# Modèle HTML intégrant le formulaire et l'affichage des résultats
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
    """Page d'accueil affichant uniquement le formulaire de recherche."""
    return render_template_string(HTML_TEMPLATE)

@app.route('/search', methods=['GET'])
def search():
    """
    Route qui traite la recherche :
    - Récupération de la requête utilisateur (mots-clés)
    - Recherche des occurrences dans les textes extraits de chaque publication
    - Affichage d’un extrait contextuel pour chaque occurrence trouvée
    """
    query = request.args.get('query', '')
    if not query:
        return render_template_string(HTML_TEMPLATE, results=[])
    
    # Division de la requête en plusieurs mots (supposés séparés par des espaces)
    words = query.split()
    
    results = []
    # Nombre de caractères à afficher avant et après le mot recherché pour donner un contexte
    context_chars = 50
    
    # Parcours de chaque publication
    for pub in publications:
        text = pub['text']
        occurrences = []
        # Pour chaque mot de la recherche, on effectue une recherche insensible à la casse
        for word in words:
            # Construction d'une expression régulière pour capter le contexte
            pattern = re.compile(r'(.{0,' + str(context_chars) + '})(' + re.escape(word) + r')(.{0,' + str(context_chars) + '})', re.IGNORECASE)
            for match in pattern.finditer(text):
                # Concaténation du contexte trouvé
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
    # Lancement de l'application Flask en mode debug
    app.run(debug=True)
