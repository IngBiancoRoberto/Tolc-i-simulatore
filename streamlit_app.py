import streamlit as st
import json
import csv
import io
import time
import uuid
import requests
from datetime import datetime, timedelta

# Usa streamlit_autorefresh per aggiornare il timer ogni secondo
from streamlit_autorefresh import st_autorefresh

# Usa extra_streamlit_components per leggere/scrivere un cookie persistente
# nel browser, necessario per riconoscere un dispositivo già registrato
# e implementare il limite di dispositivi per licenza.
import extra_streamlit_components as stx

# Configurazione Pagina
st.set_page_config(page_title="Fisica FACILE - Simulatore TOLC-I", page_icon="🎓", layout="wide")

# CSS globale: aumenta la dimensione del testo delle opzioni (st.radio) in
# tutta l'app, dato che con il font di default risultava troppo piccolo.
# Copre sia la struttura DOM più recente di Streamlit (p dentro il
# markdown container) sia quella più datata (span), per maggiore robustezza
# al variare della versione di Streamlit.
st.markdown(
    """
    <style>
        div[data-testid="stRadio"] label p,
        div[data-testid="stRadio"] label span {
            font-size: 1.15rem !important;
        }
    </style>
    """,
    unsafe_allow_html=True
)


def scrolla_in_cima_se_nuova_schermata(identificatore_schermata):
    """
    Riporta in cima sia la pagina che eventuali riquadri interni con scroll
    proprio (es. st.container(height=...)), ma SOLO quando si passa
    effettivamente a una schermata diversa da quella mostrata l'ultima volta.

    Questo controllo è fondamentale: la schermata del test viene ri-eseguita
    ogni secondo a causa di st_autorefresh (per il timer). Se lo scroll
    venisse resettato ad ogni rerun, la pagina "salterebbe" in cima ogni
    secondo anche mentre l'utente sta leggendo o rispondendo, rendendo
    l'app inutilizzabile. Confrontando l'identificatore della schermata con
    quello salvato in session_state, il reset scatta una sola volta, solo
    al cambio di sezione/schermata.
    """
    if st.session_state.get("ultima_schermata_mostrata") != identificatore_schermata:
        st.session_state["ultima_schermata_mostrata"] = identificatore_schermata
        # st.components.v1.html è deprecato: st.iframe è il sostituto
        # ufficiale, con lo stesso comportamento (JavaScript eseguibile e
        # accesso same-origin alla pagina principale tramite window.parent).
        #
        # NOTA 1: includiamo l'identificatore_schermata in un commento HTML
        # per rendere il contenuto univoco ad ogni chiamata. Senza questo
        # accorgimento, iniettando sempre lo stesso identico HTML/script, il
        # browser potrebbe considerare l'iframe "invariato" e non rieseguire
        # lo script, causando il comportamento incostante osservato.
        #
        # NOTA 2: un solo tentativo dopo 50ms non è sempre sufficiente: se la
        # nuova schermata è più lenta a disegnarsi (es. contiene molte
        # domande), lo scroll rischia di scattare troppo presto. Riprova a
        # più intervalli crescenti per coprire anche i rendering più lenti.
        st.iframe(
            f"""
            <!-- schermata: {identificatore_schermata} -->
            <script>
                function scrollaInCima() {{
                    const finestraApp = window.parent;

                    // 1. Riporta in cima la pagina principale
                    try {{
                        finestraApp.scrollTo({{top: 0, left: 0, behavior: "instant"}});
                        finestraApp.document.documentElement.scrollTop = 0;
                        finestraApp.document.body.scrollTop = 0;
                    }} catch (e) {{}}

                    // 2. Riporta in cima eventuali riquadri interni con scroll
                    //    proprio (es. il container che contiene le domande),
                    //    individuati cercando elementi con overflow verticale attivo.
                    try {{
                        const tuttiGliElementi = finestraApp.document.querySelectorAll("div");
                        tuttiGliElementi.forEach((el) => {{
                            const stile = finestraApp.getComputedStyle(el);
                            if (stile.overflowY === "auto" || stile.overflowY === "scroll") {{
                                el.scrollTop = 0;
                            }}
                        }});
                    }} catch (e) {{}}
                }}
                // Più tentativi a intervalli crescenti, per coprire sia i
                // rendering rapidi che quelli più lenti (schermate con molte
                // domande possono impiegare più tempo a disegnarsi).
                scrollaInCima();
                [50, 150, 300, 600, 1000].forEach((ritardo) => setTimeout(scrollaInCima, ritardo));
            </script>
            """,
            height=1,  # st.iframe non accetta 0: 1px è il minimo consentito, praticamente invisibile
        )

# ---------------------------------------------------------
# CONFIGURAZIONE GUMROAD
# ---------------------------------------------------------
# Sostituisci "abcde" con il permalink o l'ID del tuo prodotto Gumroad
# GUMROAD_PRODUCT_PERMALINK = "https://easyphysics101.gumroad.com/l/dummy"
PRODUCT_ID = "Or3qXjttEE-Jrb3Tt_JFCQ=="

# Numero massimo di dispositivi (browser) che possono attivare la stessa licenza.
MAX_DISPOSITIVI_PER_LICENZA = 3

# Nome del cookie usato per riconoscere un dispositivo già registrato.
COOKIE_DEVICE_ID = "tolc_device_id"


def get_cookie_manager():
    return stx.CookieManager(key="cookie_manager_device_limit")


cookie_manager = get_cookie_manager()


def verifica_licenza_gumroad(product_id: str, license_key: str, increment_uses_count: bool = True) -> dict:
    url = "https://api.gumroad.com/v2/licenses/verify"
    payload = {
        "product_id": product_id,
        "license_key": license_key.strip(),
        # Fondamentale per il limite dispositivi: quando è False controlliamo
        # solo lo stato della licenza SENZA consumare un nuovo "utilizzo".
        "increment_uses_count": "true" if increment_uses_count else "false",
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        data = response.json()
        if response.status_code == 200 and data.get("success"):
            purchase = data.get("purchase", {})
            if purchase.get("refunded") or purchase.get("chargebacked"):
                return {"success": False, "message": "Questa licenza risulta rimborsata."}
            return {
                "success": True,
                "message": "Licenza verificata con successo!",
                "email": purchase.get("email"),
                # NOTA: "uses" è un campo di primo livello nella risposta
                # Gumroad (non dentro "purchase"). Conta quante volte la
                # licenza è stata verificata con increment_uses_count=true.
                "uses": data.get("uses", 0),
            }
        else:
            return {"success": False, "message": "Chiave di licenza non valida."}
    except Exception as e:
        return {"success": False, "message": f"Errore di connessione: {e}"}


# ---------------------------------------------------------
# INIZIALIZZAZIONE SESSION STATE
# ---------------------------------------------------------
if "licenza_valida" not in st.session_state:
    st.session_state.licenza_valida = False

if "sezione_attuale_idx" not in st.session_state:
    st.session_state.sezione_attuale_idx = 0

if "risposte_totali" not in st.session_state:
    st.session_state.risposte_totali = {}

if "test_completato" not in st.session_state:
    st.session_state.test_completato = False

if "tempo_fine_sezione" not in st.session_state:
    st.session_state.tempo_fine_sezione = None


# ---------------------------------------------------------
# SCHERMATA 0: VERIFICA LICENZA (GATEKEEPER)
# ---------------------------------------------------------
if not st.session_state.licenza_valida:
    st.title("🎓 FISICA FACILE - Simulatore TOLC-I CISIA")
    st.subheader("Attivazione Prodotto")
    st.write("Inserisci la tua **License Key** di Gumroad ricevuta via email al momento dell'acquisto per sbloccare la simulazione.")

    with st.form("form_licenza"):
        user_key = st.text_input("Chiave di Licenza Gumroad:", placeholder="Es. XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX", type="password")
        submit_key = st.form_submit_button("Verifica e Accedi 🔓")

        if submit_key:
            if not user_key:
                st.warning("Per favore inserisci una chiave di licenza.")
            else:
                with st.spinner("Verifica licenza in corso con Gumroad..."):
                    # Passo 1: verifichiamo la licenza SENZA incrementare il
                    # contatore di utilizzi, solo per controllare che sia
                    # valida e vedere quanti dispositivi sono già registrati.
                    risultato = verifica_licenza_gumroad(PRODUCT_ID, user_key, increment_uses_count=False)

                if not risultato["success"]:
                    st.error(risultato["message"])
                else:
                    device_id_esistente = cookie_manager.get(cookie=COOKIE_DEVICE_ID)

                    if device_id_esistente:
                        # Questo browser ha già un cookie: dispositivo già
                        # registrato in passato, nessun nuovo slot da consumare.
                        st.session_state.licenza_valida = True
                        st.success(f"Bentornato! Licenza attivata per: {risultato.get('email')}")
                        time.sleep(1)
                        st.rerun()
                    elif risultato["uses"] >= MAX_DISPOSITIVI_PER_LICENZA:
                        # Dispositivo mai visto su questo browser, ma il
                        # limite di dispositivi per questa licenza è già raggiunto.
                        st.error(
                            f"⚠️ Hai raggiunto il numero massimo di dispositivi "
                            f"({MAX_DISPOSITIVI_PER_LICENZA}) consentiti per questa "
                            f"licenza. Contatta l'assistenza se devi attivare un "
                            f"nuovo dispositivo."
                        )
                    else:
                        # C'è ancora spazio: registriamo il nuovo dispositivo
                        # incrementando davvero il contatore su Gumroad...
                        with st.spinner("Registrazione nuovo dispositivo..."):
                            registrazione = verifica_licenza_gumroad(PRODUCT_ID, user_key, increment_uses_count=True)

                        if not registrazione["success"]:
                            st.error(registrazione["message"])
                        else:
                            # ...e salviamo un cookie persistente sul browser
                            # per riconoscerlo alle prossime visite.
                            nuovo_device_id = str(uuid.uuid4())
                            scadenza = datetime.now() + timedelta(days=365)
                            cookie_manager.set(
                                COOKIE_DEVICE_ID,
                                nuovo_device_id,
                                expires_at=scadenza,
                                key="set_tolc_device_id",
                            )
                            st.session_state.licenza_valida = True
                            st.success(f"Benvenuto! Licenza attivata per: {registrazione.get('email')}")
                            time.sleep(1)
                            st.rerun()

    st.markdown("---")
    st.caption("Non hai ancora una chiave? [Acquista la guida e le simulazioni su Gumroad](https://easyphysics101.gumroad.com/)")
    st.stop() # Interrompe l'esecuzione dello script se non si è verificati


# ---------------------------------------------------------
# CARICAMENTO DATI
# ---------------------------------------------------------
@st.cache_data
def carica_dati():
    with open("TOLC-I-Domande.json", "r", encoding="utf-8") as f:
        return json.load(f)

data = carica_dati()
sezioni = data["sezioni"]


def ottieni_quesiti_sezione(sezione):
    """
    Restituisce l'elenco APPIATTITO dei quesiti di una sezione.

    La maggior parte delle sezioni (Matematica, Scienze, Logica) ha una
    lista diretta "quesiti". La sezione di Comprensione Verbale, invece, ha
    una lista di "testi", ciascuno con un proprio elenco di quesiti annidato
    (un brano lungo seguito dalle domande che vi fanno riferimento). Questa
    funzione uniforma le due strutture, così che punteggio, dashboard ed
    export CSV possano trattare qualunque sezione allo stesso modo, senza
    doversi preoccupare di come sono organizzati i quesiti al suo interno.
    """
    if "testi" in sezione:
        quesiti = []
        for testo in sezione["testi"]:
            quesiti.extend(testo["quesiti"])
        return quesiti
    return sezione["quesiti"]


def renderizza_quesito(q, numero_visualizzato):
    """Disegna un singolo quesito (testo, eventuale immagine, opzioni con
    lettera A/B/C... e salvataggio della risposta), riutilizzabile sia dalle
    sezioni con elenco piatto di quesiti sia da quelle strutturate a testi."""
    st.markdown(f"#### Quesito {numero_visualizzato}")
    st.markdown(f"##### {q["testo"]}")

    if q.get("immagine_url"):
        st.image(q["immagine_url"], width=400)

    opzioni_totali = ["Omessa"] + q["opzioni"]
    risposta_precedente = st.session_state.risposte_totali.get(q["id"], "Omessa")

    def formatta_opzione(opzione, opzioni_quesito=q["opzioni"]):
        """Antepone una lettera (A, B, C...) al testo dell'opzione,
        solo per la visualizzazione: il valore salvato in
        session_state resta il testo originale dell'opzione,
        così tutti i confronti già esistenti nel codice
        (indice_corretto, export CSV, ecc.) continuano a funzionare."""
        if opzione == "Omessa":
            return "Omessa"
        lettera = chr(65 + opzioni_quesito.index(opzione))
        return f"{lettera}) {opzione}"

    scelta = st.radio(
        f"Seleziona la risposta per il Quesito {numero_visualizzato}:",
        options=opzioni_totali,
        index=opzioni_totali.index(risposta_precedente),
        key=f"radio_{q['id']}",
        format_func=formatta_opzione,
        label_visibility="collapsed"
    )

    st.session_state.risposte_totali[q["id"]] = scelta
    st.divider()


def renderizza_testo_collassabile(testo_obj):
    """
    Mostra il brano lungo della Comprensione Verbale dentro un riquadro che
    l'utente può chiudere con un bottone (per concentrarsi sulle domande) e
    riaprire in qualunque momento per rileggerlo, emulando il comportamento
    del sito CISIA. Lo stato aperto/chiuso è salvato in session_state con
    una chiave dedicata per ogni testo, quindi resta coerente anche tra un
    rerun e l'altro (compresi quelli automatici del timer).
    """
    chiave_stato = f"testo_aperto_{testo_obj['id']}"
    if chiave_stato not in st.session_state:
        st.session_state[chiave_stato] = True  # aperto di default

    st.markdown(f"### 📖 {testo_obj['titolo']}")

    if st.session_state[chiave_stato]:
        with st.container(border=True):
            st.markdown(testo_obj["corpo"])
        if st.button("🔽 Chiudi il testo e rispondi alle domande", key=f"chiudi_{testo_obj['id']}"):
            st.session_state[chiave_stato] = False
            st.rerun()
    else:
        st.info("Il testo è chiuso. Puoi riaprirlo in qualsiasi momento per rileggerlo.")
        if st.button("🔼 Riapri il testo", key=f"apri_{testo_obj['id']}"):
            st.session_state[chiave_stato] = True
            st.rerun()

    st.divider()


def passa_a_sezione_successiva():
    totale_sezioni = len(sezioni)
    if st.session_state.sezione_attuale_idx < totale_sezioni - 1:
        st.session_state.sezione_attuale_idx += 1
        st.session_state.tempo_fine_sezione = None
    else:
        st.session_state.test_completato = True
    st.session_state.scaduto_timestamp = None
    st.rerun()


if "mostra_dialog_avanzamento" not in st.session_state:
    st.session_state.mostra_dialog_avanzamento = False


@st.dialog("Conferma", dismissible=False)
def conferma_avanzamento_dialog():
    idx_corrente = st.session_state.sezione_attuale_idx
    ultima_sezione = idx_corrente >= len(sezioni) - 1

    if ultima_sezione:
        st.write(
            "Stai per **terminare il test** e inviarlo per la valutazione. "
            "Una volta confermato non potrai più tornare indietro a "
            "modificare le tue risposte."
        )
        etichetta_conferma = "🏁 Sì, termina il test"
    else:
        prossima_sezione = sezioni[idx_corrente + 1]["nome"]
        st.write(
            f"Stai per passare alla sezione **'{prossima_sezione}'**. "
            "Una volta confermato non potrai più tornare indietro a "
            "modificare le risposte della sezione corrente."
        )
        etichetta_conferma = "Sì, procedi ➔"

    col_conferma, col_annulla = st.columns(2)
    with col_conferma:
        if st.button(etichetta_conferma, type="primary", use_container_width=True):
            st.session_state.mostra_dialog_avanzamento = False
            passa_a_sezione_successiva()
    with col_annulla:
        if st.button("Annulla", use_container_width=True):
            st.session_state.mostra_dialog_avanzamento = False
            st.rerun()


def trova_fascia_punteggio(punteggio_totale: float, fasce: list) -> dict | None:
    """
    Restituisce la fascia (posizionamento + consiglio) corrispondente al
    punteggio totale, leggendo le soglie dal JSON (chiave "fasce_punteggio")
    invece di averle scritte fisse nel codice.

    Ogni fascia ha:
      - punteggio_min: soglia inclusa (null = nessun limite inferiore)
      - punteggio_max: soglia esclusa (null = nessun limite superiore)
    """
    for fascia in fasce:
        soglia_min = fascia.get("punteggio_min")
        soglia_max = fascia.get("punteggio_max")

        supera_min = soglia_min is None or punteggio_totale >= soglia_min
        sotto_max = soglia_max is None or punteggio_totale < soglia_max

        if supera_min and sotto_max:
            return fascia

    return None


def esegui_logout():
    """Resetta la licenza E tutto il progresso della simulazione,
    così al rientro l'utente riparte sempre dalla prima sezione."""
    st.session_state.licenza_valida = False
    st.session_state.sezione_attuale_idx = 0
    st.session_state.risposte_totali = {}
    st.session_state.test_completato = False
    st.session_state.tempo_fine_sezione = None
    st.session_state.scaduto_timestamp = None
    st.session_state.mostra_dialog_uscita = False
    st.rerun()


@st.dialog("Conferma uscita", dismissible=False)
def conferma_uscita_dialog():
    st.write(
        "Sei sicuro di voler uscire? Il progresso della simulazione attuale "
        "andrà perso e alla prossima verifica della licenza dovrai "
        "ricominciare dalla prima sezione."
    )
    col_conferma, col_annulla = st.columns(2)
    with col_conferma:
        if st.button("Sì, esci", type="primary", use_container_width=True):
            esegui_logout()
    with col_annulla:
        if st.button("Annulla", use_container_width=True):
            st.session_state.mostra_dialog_uscita = False
            st.rerun()


# Inizializza il flag che tiene traccia dell'apertura del dialog di conferma.
# Va salvato in session_state perché st_autorefresh forza un rerun ogni
# secondo: senza questo flag, al rerun il click sul pulsante andrebbe perso
# e il dialog sparirebbe subito.
if "mostra_dialog_uscita" not in st.session_state:
    st.session_state.mostra_dialog_uscita = False

# Sidebar con opzione per disconnettersi / cambio licenza
with st.sidebar:
    st.write("🔐 **Stato Licenza:** Attiva")
    if st.button("Esci / Cambia Licenza"):
        st.session_state.mostra_dialog_uscita = True
        st.rerun()

# Il dialog viene richiamato ad OGNI rerun (non solo al click) finché
# mostra_dialog_uscita resta True: così sopravvive anche ai rerun
# automatici generati da st_autorefresh, e resta a video finché l'utente
# non sceglie "Sì, esci" o "Annulla".
if st.session_state.mostra_dialog_uscita:
    conferma_uscita_dialog()


# ---------------------------------------------------------
# SCHERMATA 1: TEST COMPLETATO
# ---------------------------------------------------------
if st.session_state.test_completato:
    schermata_appena_aperta = st.session_state.get("ultima_schermata_mostrata") != "risultati"
    scrolla_in_cima_se_nuova_schermata("risultati")

    st.title("📊 Risultato Finale Simulazione CISIA")

    # I palloncini devono festeggiare una volta sola, al primo ingresso in
    # questa schermata. Senza questo controllo, ripartirebbero ad ogni
    # rerun dello script — compreso quello scatenato dal click sul
    # pulsante "Scarica CSV" — perché st.balloons() veniva chiamato
    # incondizionatamente ogni volta che questo blocco viene eseguito.
    if schermata_appena_aperta:
        st.balloons()
    
    punteggio_totale = 0.0
    trappole_subite = []
    righe_csv = []

    for sez in sezioni:
        st.subheader(f"Sezione: {sez['nome']}")
        punti_sezione = 0.0
        corrette = 0
        errate = 0
        omesse = 0
        
        for numero_domanda, q in enumerate(ottieni_quesiti_sezione(sez), 1):
            risposta_data = st.session_state.risposte_totali.get(q["id"], "Omessa")
            
            if risposta_data == "Omessa":
                punti_sezione += data["test_info"]["punteggio_omessa"]
                omesse += 1
                righe_csv.append({
                    "Sezione": sez["nome"],
                    "Numero Domanda": numero_domanda,
                    "Opzione Scelta": "",
                    "Esito": "omesso"
                })
            else:
                idx_scelto = q["opzioni"].index(risposta_data)
                # Stessa lettera (A, B, C...) mostrata nella schermata del test:
                # deriviamo dalla posizione dell'opzione nell'array, così
                # rimane coerente anche se in futuro cambia il numero di opzioni.
                lettera_scelta = chr(65 + idx_scelto)

                if idx_scelto == q["indice_corretto"]:
                    punti_sezione += data["test_info"]["punteggio_corretta"]
                    corrette += 1
                    esito = "corretto"
                else:
                    punti_sezione += data["test_info"]["punteggio_sbagliata"]
                    errate += 1
                    esito = "errato"

                    # NOTA: non ogni risposta sbagliata è una "trappola".
                    # "trappole" nel JSON è un dizionario {indice_opzione: testo},
                    # quindi solo le opzioni effettivamente presenti come chiave
                    # vengono conteggiate come trappola. Le chiavi sono stringhe
                    # perché in JSON le chiavi di un oggetto sono sempre testo.
                    testo_trappola = q.get("trappole", {}).get(str(idx_scelto))
                    if testo_trappola:
                        trappole_subite.append({
                            "sezione": sez["nome"],
                            "numero_domanda": numero_domanda,
                            "argomento": q["argomento"],
                            "trappola": testo_trappola
                        })

                righe_csv.append({
                    "Sezione": sez["nome"],
                    "Numero Domanda": numero_domanda,
                    "Opzione Scelta": lettera_scelta,
                    "Esito": esito
                })
                    
        punteggio_totale += punti_sezione

        col_punteggio, col_corrette, col_errate, col_omesse = st.columns(4)
        with col_punteggio:
            st.metric(label="Punteggio Parziale", value=f"{punti_sezione:.2f} pt")
        with col_corrette:
            st.metric(label="✅ Corrette", value=corrette)
        with col_errate:
            st.metric(label="❌ Errate", value=errate)
        with col_omesse:
            st.metric(label="➖ Omesse", value=omesse)

        st.divider()

    st.markdown(
        f"""
        <div style="text-align:center; padding: 1.75rem 1rem; margin: 1.5rem 0;
                    border: 3px solid #FF4B4B; border-radius: 16px;
                    background-color: rgba(255, 75, 75, 0.06);">
            <div style="font-size: 1.3rem; font-weight: 600; letter-spacing: 0.05em;
                        text-transform: uppercase; color: #888;">
                Punteggio Totale
            </div>
            <div style="font-size: 4rem; font-weight: 800; line-height: 1.1; color: #FF4B4B;">
                {punteggio_totale:.2f}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    fascia = trova_fascia_punteggio(punteggio_totale, data.get("fasce_punteggio", []))

    if fascia:
        st.subheader(f"📍 Posizionamento: {fascia['posizionamento']}")
        st.info(f"💡 **Consiglio:** {fascia['consiglio']}")
    else:
        # Nessuna fascia configurata nel JSON che copra questo punteggio:
        # non blocchiamo la visualizzazione del resto dei risultati.
        st.caption("Nessuna fascia di posizionamento configurata per questo punteggio.")

    # --- ESPORTAZIONE RISULTATI IN CSV ---
    buffer_csv = io.StringIO()
    scrittore_csv = csv.DictWriter(
        buffer_csv,
        fieldnames=["Sezione", "Numero Domanda", "Opzione Scelta", "Esito"]
    )
    scrittore_csv.writeheader()
    scrittore_csv.writerows(righe_csv)

    st.download_button(
        label="⬇️ Scarica i tuoi risultati in CSV",
        data=buffer_csv.getvalue(),
        file_name="risultati_simulazione_tolc.csv",
        mime="text/csv"
    )

    if trappole_subite:
        st.warning("⚠️ **Analisi Diagnostica delle Trappole Subite:**")
        for t in trappole_subite:
            st.write(f"- **[{t['sezione']} - Domanda {t['numero_domanda']} - {t['argomento']}]**: {t['trappola']}")

    if st.button("🔄 Ricomincia Nuova Simulazione"):
        st.session_state.sezione_attuale_idx = 0
        st.session_state.risposte_totali = {}
        st.session_state.test_completato = False
        st.session_state.tempo_fine_sezione = None
        st.session_state.scaduto_timestamp = None
        st.rerun()

# ---------------------------------------------------------
# SCHERMATA 2: SVOLGIMENTO TEST
# ---------------------------------------------------------
else:
    # NOTA SUL BUG DELLE FINESTRE MODALI: st_autorefresh forza un rerun
    # completo ogni secondo per aggiornare il timer. Se un dialog di
    # conferma (uscita o passaggio di sezione) è aperto, ogni rerun
    # ripete la chiamata alla funzione del dialog (perché il flag in
    # session_state resta True), che quindi si "ri-genera" da capo ogni
    # secondo: da qui il lampeggio. Inoltre, se l'utente chiude il dialog
    # cliccando fuori, questa è un'azione solo lato client di cui il
    # nostro codice Python non si accorge: il flag resta True, quindi al
    # tick successivo il dialog riappare comunque.
    #
    # La soluzione è sospendere il tick del timer finché un dialog di
    # conferma è aperto: senza rerun periodici, il dialog resta esattamente
    # come l'utente lo lascia (aperto finché non sceglie un'opzione, o
    # chiuso se clicca fuori) invece di essere ridisegnato ogni secondo.
    # Il tempo reale continua comunque a scorrere in background (si basa
    # su un timestamp assoluto, non sui rerun), quindi il conto alla
    # rovescia resta corretto anche se il display non si aggiorna per i
    # pochi secondi in cui l'utente sta decidendo.
    dialog_di_conferma_aperto = (
        st.session_state.get("mostra_dialog_uscita")
        or st.session_state.get("mostra_dialog_avanzamento")
    )
    if not dialog_di_conferma_aperto:
        st_autorefresh(interval=1000, key="timer_autorefresh")

    idx_attuale = st.session_state.sezione_attuale_idx
    sezione_corrente = sezioni[idx_attuale]
    totale_sezioni = len(sezioni)
    quesiti_sezione = ottieni_quesiti_sezione(sezione_corrente)
    totale_domande_sez = len(quesiti_sezione)

    # Reset dello scroll SOLO quando si entra in una sezione diversa da quella
    # mostrata l'ultima volta, non ad ogni rerun del timer (vedi commento
    # nella funzione per i dettagli).
    scrolla_in_cima_se_nuova_schermata(f"sezione_{idx_attuale}")

# ---------------------------------------------------------
# GESTIONE TIMER E SCADENZA
# ---------------------------------------------------------
    if st.session_state.tempo_fine_sezione is None:
        durata_secondi = sezione_corrente["tempo_minuti"] * 60
        st.session_state.tempo_fine_sezione = time.time() + durata_secondi

    secondi_rimasti = int(st.session_state.tempo_fine_sezione - time.time())

    # Inizializza il timestamp di inizio "tempo scaduto" se non esiste
    if "scaduto_timestamp" not in st.session_state:
        st.session_state.scaduto_timestamp = None

    # NOTA: la pausa di 3 secondi NON viene gestita con time.sleep().
    # st_autorefresh forza un rerun lato client ogni secondo indipendentemente
    # da cosa sta facendo lo script: uno sleep() bloccante potrebbe essere
    # interrotto a metà da un rerun esterno, lasciando lo stato inconsistente
    # (schermata che sembra bloccata). Usiamo invece un timestamp salvato in
    # session_state e confrontato con time.time() ad ogni rerun: è l'autorefresh
    # stesso a "far scorrere" i 3 secondi, un rerun alla volta.
    if secondi_rimasti <= 0:
        # Primo rerun in cui rileviamo lo scadere del tempo: salviamo il momento
        if st.session_state.scaduto_timestamp is None:
            st.session_state.scaduto_timestamp = time.time()

        tempo_trascorso = time.time() - st.session_state.scaduto_timestamp

        st.error("⏰ **Tempo scaduto per questa sezione!** Invio automatico delle risposte in corso...")

        # Dopo 3 secondi dallo scadere del tempo, passiamo alla sezione successiva
        if tempo_trascorso >= 4:
            st.session_state.scaduto_timestamp = None
            passa_a_sezione_successiva()

    # --- INTESTAZIONE ---
    st.title(data["test_info"]["titolo"])
    st.progress((idx_attuale) / totale_sezioni)
    st.caption(f"Sezione {idx_attuale + 1} di {totale_sezioni}: **{sezione_corrente['nome']}**")
    st.divider()

    # --- LAYOUT A 2 COLONNE ---
    col_quesiti, col_dashboard = st.columns([3, 1], gap="large")

    with col_dashboard:
        st.subheader("⏱️ Stato Prova")
        
        # NOTA: usiamo un valore "clampato" a 0 per la sola visualizzazione.
        # secondi_rimasti può diventare negativo durante i secondi di
        # transizione dopo la scadenza del tempo. In Python, il modulo (%)
        # su un numero negativo restituisce un resto POSITIVO (es. -1 % 60 = 59),
        # quindi senza questo clamp il timer "saltava" a 00:59 e sembrava
        # ripartire da capo invece di restare fermo su 00:00.
        secondi_rimasti_display = max(0, secondi_rimasti)
        minuti = secondi_rimasti_display // 60
        secondi = secondi_rimasti_display % 60
        timer_str = f"{minuti:02d}:{secondi:02d}"
        
        if secondi_rimasti < 60:
            st.error(f"⌛ **Tempo Rimanente:**\n# {timer_str}")
        else:
            st.metric(label="Tempo Rimanente Sezione", value=timer_str)

        risposte_date = sum(1 for q in quesiti_sezione if st.session_state.risposte_totali.get(q["id"], "Omessa") != "Omessa")

        st.metric(
            label="Avanzamento Risposte", 
            value=f"{risposte_date} / {totale_domande_sez}"
        )
        st.progress(risposte_date / totale_domande_sez)

    with col_quesiti:
        with st.container(height=600):
            st.header(f"📝 Sezione: {sezione_corrente['nome']}")

            if "testi" in sezione_corrente:
                # Sezione strutturata come Testo 1 - Domande - Testo 2 - Domande...
                numero_domanda_corrente = 0
                for testo_obj in sezione_corrente["testi"]:
                    renderizza_testo_collassabile(testo_obj)
                    for q in testo_obj["quesiti"]:
                        numero_domanda_corrente += 1
                        renderizza_quesito(q, numero_domanda_corrente)
            else:
                # Sezioni con elenco piatto di quesiti (Matematica, Scienze, Logica)
                for idx, q in enumerate(quesiti_sezione, 1):
                    renderizza_quesito(q, idx)

        if idx_attuale < totale_sezioni - 1:
            testo_bottone = f"Conferma Sezione e Passa a '{sezioni[idx_attuale + 1]['nome']}' ➔"
        else:
            testo_bottone = "🏁 Termina il Test e Invia per la Valutazione"

        if st.button(testo_bottone, type="primary"):
            st.session_state.mostra_dialog_avanzamento = True
            st.rerun()

    # Il dialog viene richiamato ad OGNI rerun (non solo al click) finché
    # mostra_dialog_avanzamento resta True: così sopravvive anche ai rerun
    # automatici generati da st_autorefresh (il timer), esattamente come per
    # il dialog di conferma uscita.
    if st.session_state.get("mostra_dialog_avanzamento"):
        conferma_avanzamento_dialog()
