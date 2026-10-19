// Liquid Mouse — client, 1/4: nucleo (connessione, autenticazione, Motion, schede).
//
// Il client è diviso in quattro script classici (non moduli), tutti con defer e
// nell'ordine di index.html: app-core.js, app-touchpad.js, app-terminal.js,
// app-files.js. Condividono lo scope globale (let/const e function di primo
// livello). Regola: mentre un file viene eseguito usa solo ciò che dichiara lui
// o un file precedente; le funzioni degli altri file le chiama soltanto da
// gestori di eventi e messaggi, quando la pagina è già caricata. Per questo il
// nucleo viene per primo e nomina il resto solo dentro HANDLERS e switchTab.
//
// Nel markup non ci sono attributi onclick= inline (la CSP vieta gli script
// inline): gli eventi si legano qui e negli altri file.

    // --- LOGICA CLIENT ---
    const statusDiv = document.getElementById('status');
    const hiddenInput = document.getElementById('hidden-input');
    const configPanel = document.getElementById('configPanel');
    const ipInput = document.getElementById('ipInput');
    const pinInput = document.getElementById('pinInput');
    const connectBtn = document.getElementById('connectBtn');
    const certHint = document.getElementById('cert-hint');
    const certLink = document.getElementById('cert-link');
    let ws = null;
    let pingInterval = null;   // a scope modulo: pulito da closeWS() (no leak)

    // --- MOTION: animazioni (motion.dev, static/vendor/motion.js) ---
    // Solo abbellimento. Se motion.js non si carica o il sistema chiede meno
    // movimento, anima() non fa nulla e ritorna null: la pagina resta
    // identica, e senza Motion tornano le animazioni CSS di riserva (app.css,
    // html:not(.motion)). Mai sul percorso del touchpad: lì ogni millisecondo
    // è latenza del cursore. Unico punto che tocca il global `Motion`.
    const MotionLib = (window.Motion && typeof window.Motion.animate === 'function')
        ? window.Motion : null;
    const menoMovimento = window.matchMedia
        ? window.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
    if (MotionLib) document.documentElement.classList.add('motion');

    // Due tempi per tutto il client: una molla corta per ciò che entra, una
    // curva rapida per dissolvenze e uscite. Sotto i 300 ms: niente attese.
    const MOLLA = { type: 'spring', bounce: 0.2, visualDuration: 0.26 };
    const RAPIDA = { duration: 0.18, ease: [0.22, 1, 0.36, 1] };
    const SCAGLIONI_MAX = 12;   // oltre, gli elementi compaiono senza attesa

    function anima(el, keyframes, opzioni) {
        if (!MotionLib || menoMovimento.matches || !el) return null;
        if (el.length === 0) return null;
        try { return MotionLib.animate(el, keyframes, opzioni); } catch (_) { return null; }
    }
    // Ingresso scaglionato dei figli di un elenco appena ridisegnato.
    function animaElenco(contenitore) {
        if (!MotionLib) return null;
        const figli = Array.from(contenitore.children).slice(0, SCAGLIONI_MAX);
        return anima(figli, { opacity: [0, 1], y: [8, 0] },
                     { ...MOLLA, delay: MotionLib.stagger(0.03) });
    }
    // Dopo un'animazione mancata (Motion assente, meno movimento attivato a
    // metà) gli stili inline lasciati da quella precedente vanno tolti, o un
    // pannello resterebbe trasparente.
    function pulisciStile(el) { el.style.opacity = ''; el.style.transform = ''; }

    // Pressione: il pannello si abbassa sotto il dito e torna con una molla.
    // Delegato su document e solo su pointerdown/up, mai su pointermove; il
    // touchpad non è nell'elenco.
    const PREMIBILI = '.menu-btn-item, #btn-menu, .tkey, .session-card-btn, ' +
        '.session-card-close, .fbtn, #term-back, #files-back, .config-btn';
    let premuto = null;
    function rilascia() {
        if (premuto) anima(premuto, { scale: 1 }, { type: 'spring', bounce: 0.45, visualDuration: 0.2 });
        premuto = null;
    }
    if (MotionLib) {
        document.addEventListener('pointerdown', (e) => {
            const el = e.target.closest && e.target.closest(PREMIBILI);
            if (!el) return;
            premuto = el;
            anima(el, { scale: 0.95 }, { duration: 0.08, ease: 'easeOut' });
        }, { passive: true });
        ['pointerup', 'pointercancel'].forEach(tipo =>
            document.addEventListener(tipo, rilascia, { passive: true }));
    }

    // Colore della riga di stato: una classe CSS (ok / warn / err) invece di un
    // colore scritto qui, così la palette resta solo in app.css. Si anima solo
    // al cambio di tipo, non a ogni pong (uno ogni 5 s).
    function setStatus(text, kind) {
        const prima = statusDiv.className;
        statusDiv.textContent = text;
        statusDiv.className = kind || '';
        if (statusDiv.className === prima) return;
        if (kind === 'err') anima(statusDiv, { x: [0, -5, 5, -3, 0], opacity: [0.4, 1] }, { duration: 0.34 });
        else anima(statusDiv, { opacity: [0.35, 1] }, { duration: 0.3 });
    }

    function loadPIN() { return localStorage.getItem('liquidMousePIN') || ''; }
    function savePIN(p) { if (p) localStorage.setItem('liquidMousePIN', p); }

    function switchTab(name) {
        // La sessione terminal resta attaccata al cambio tab: xterm conserva
        // lo stato e il server continua a inviare output. Niente detach qui
        // (era la causa della duplicazione: re-attach → replay del ring).
        const content = document.getElementById('content-' + name);
        const btn = document.getElementById('tab-' + name);
        const giaAperta = btn && btn.classList.contains('active');
        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
        if (content) content.classList.add('active');
        if (btn) btn.classList.add('active');
        if (!giaAperta) {
            // Solo opacità sulla cartella: una trasformazione la renderebbe il
            // riferimento dei figli position:fixed (menu, configurazione,
            // input della tastiera), che durante l'animazione si sposterebbero.
            anima(content, { opacity: [0, 1] }, RAPIDA);
            if (btn) anima(btn.querySelectorAll('.tab-num, .tab-name'), { y: [3, 0] }, MOLLA);
        }
        document.body.classList.toggle('term-open', name === 'terminal');
        if (name === 'terminal') onTerminalTabOpen();
        if (name === 'files') onFilesTabOpen();
    }

    // Niente onclick= inline nel markup: la CSP (net/static.py) non ammette script
    // inline, quindi le linguette si legano qui con data-tab.
    document.querySelectorAll('.tab-btn[data-tab]').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    function loadIP() { return localStorage.getItem('liquidMouseIP') || ''; }
    function saveIP(ip) { localStorage.setItem('liquidMouseIP', ip); }

    let reconnectAttempts = 0;
    const MAX_RECONNECTS = 5;

    let connectionTimeout;
    let disconnectHandled = false;

    function closeWS() {
        clearInterval(pingInterval);
        pingInterval = null;
        if (ws) { ws.onclose = null; ws.onerror = null; ws.close(); }
    }

    // wss remoto (pagina servita via HTTPS) oppure ws locale (HTTP:8000).
    // Il wss usa la STESSA porta della pagina (porta unica remota): così il
    // certificato già accettato per la pagina vale anche per il socket e
    // basta un solo port-forward. Porte diverse = fallimento silenzioso.
    function buildWsUrl(ip) {
        if (window.location.protocol === 'https:') {
            const port = window.location.port || '443';
            return `wss://${ip.trim()}:${port}`;
        }
        return `ws://${ip.trim()}:8765`;
    }

    function isValidIPv4(s) {
        const parts = s.split('.');
        if (parts.length !== 4) return false;
        return parts.every(p => /^\d{1,3}$/.test(p) && parseInt(p, 10) >= 0 && parseInt(p, 10) <= 255);
    }
    function isValidHostname(s) {
        return /^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/.test(s);
    }

    // --- TASTIERA: contratto (tests/test_kbd_diff.py) ---
    // Cosa mandare al PC quando il campo nascosto passa da `prev` a `val`:
    // si cancella la parte tolta e si scrive la nuova coda, dopo il prefisso
    // comune. Il confronto per sola lunghezza perdeva le sostituzioni della
    // correzione automatica ("teh" -> "the"). Si lavora per punti di codice:
    // un'emoji e' un solo backspace e una coppia surrogata non si spezza.
    function diffTastiera(prev, val) {
        const a = Array.from(prev), b = Array.from(val);
        let i = 0;
        while (i < a.length && i < b.length && a[i] === b[i]) i++;
        return { del: a.length - i, add: b.slice(i).join('') };
    }
    // --- fine contratto ---

    // --- AUTH: contratto (tests/test_auth_client.py) ---
    // Dopo un PIN errato o un blocco nessuna riconnessione automatica (timer o
    // risveglio del telefono) deve rimandare lo stesso PIN: al quinto errore il
    // server blocca l'IP per 30 minuti. Si riabilita solo da un gesto
    // dell'utente: "connetti" o la modifica del PIN.
    function makeAuthGate() {
        let failed = false;
        return {
            fail() { failed = true; },
            reset() { failed = false; },
            canAutoReconnect() { return !failed; },
        };
    }
    // --- fine contratto ---
    const authGate = makeAuthGate();

    // --- PIN: contratto (tests/test_auth_client.py) ---
    // Il QR porta il PIN nel fragment (#pin=...): il browser non lo manda nella
    // richiesta HTTP, quindi non finisce nei log del tunnel, del router o di
    // un proxy, né nell'header Referer. `?pin=` resta accettato per i QR e i
    // segnalibri vecchi. Ritorna il PIN (o null) e l'indirizzo ripulito da
    // usare con history.replaceState, così non resta nella barra né nella cronologia.
    function pinFromUrl(href) {
        let url;
        try { url = new URL(href); } catch (_) { return { pin: null, clean: href }; }
        const frag = new URLSearchParams(url.hash.slice(1));
        const pin = frag.get('pin') || url.searchParams.get('pin') || null;
        url.searchParams.delete('pin');
        frag.delete('pin');
        const resto = frag.toString();
        url.hash = resto ? '#' + resto : '';
        return { pin: pin, clean: url.toString() };
    }
    // --- fine contratto ---

    // Manda il PIN (remoto all'apertura, LAN quando il server risponde
    // `auth_required` perché `lan_require_pin` è acceso sul PC). Senza PIN non
    // si tenta nulla: si ferma con un errore e si riapre la configurazione.
    function sendAuth() {
        const pin = pinInput.value.trim() || loadPIN();
        if (!pin) {
            stopWithError('pin richiesto');
            pinInput.focus();
            return;
        }
        ws.send(JSON.stringify({ type: 'auth', pin }));
        setStatus('autenticazione...', 'warn');
    }

    function onAuthenticated(conn) {
        setStatus('connessione stabilita', 'ok');
        configPanel.classList.add('hidden'); saveIP(conn.ip.trim());
        savePIN(pinInput.value.trim());
        clearInterval(pingInterval);
        pingInterval = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                conn.pingTimestamp = Date.now();
                ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 5000);
        // Dopo una riconnessione, se il tab terminal è attivo e c'è una
        // sessione, riaggancia (il server ha sganciato il ws morto).
        if (termSessionId && document.getElementById('content-terminal').classList.contains('active')) {
            attached = false;
            attachSession(termSessionId);
        }
        // Il server chiude le connessioni SFTP con il socket: dopo una
        // riconnessione si riparte dai profili.
        filesReset();
        // Deep-link finestra PC (?term=<id>): apri il terminale e aggancia.
        if (pendingTermId) {
            termSessionId = pendingTermId;
            pendingTermId = null;
            switchTab('terminal');
        }
    }

    // --- MESSAGGI DAL SERVER: una tabella e un solo punto di smistamento ---
    // Chiave = `type` del messaggio JSON; il gestore riceve (msg, conn). Gli
    // `sftp_*` vanno tutti a handleFilesMessage (vedi dispatchMessage).
    // Tabella e non catena di if/else: aggiungere un tipo è una riga, e non c'è
    // più un blocco in cui un `break` fuori posto (SyntaxError, bug v2.2.x:
    // client morto su "In attesa...") possa uccidere l'intero script.
    const HANDLERS = new Map(Object.entries({
        auth_required: () => sendAuth(),
        auth_ok: (msg, conn) => onAuthenticated(conn),
        auth_fail: (msg) => {
            const rem = msg.remaining > 0 ? ` (${msg.remaining} tentativi rimasti)` : '';
            authGate.fail();
            stopWithError(`pin errato${rem}`);
        },
        auth_blocked: () => {
            authGate.fail();
            stopWithError('bloccato — riprova tra 30 min');
        },
        pong: (msg, conn) => {
            if (!(conn.pingTimestamp > 0)) return;
            const rtt = Date.now() - conn.pingTimestamp;
            setStatus(`connesso ${rtt}ms`, rtt < 50 ? 'ok' : rtt < 150 ? 'warn' : 'err');
        },
        term_sessions: (msg) => {
            termShells = parseShells(msg.shells);
            renderSessionPicker(msg.sessions);
        },
        term_created: (msg) => {
            termSessionId = msg.id;
            termSessionCmd = termPendingCmd || termShellChoice;
            termPendingCmd = '';
            attachSession(msg.id);
        },
        term_closed: (msg) => {
            if (msg.id && msg.id !== termSessionId) return;
            document.getElementById('tab-terminal-dot').style.display = 'none';
            document.getElementById('terminal-active').classList.remove('visible');
            document.getElementById('session-picker').style.display = '';
            // Chiusa con la ×: niente banner d'errore.
            if (!chiuseDaQui.delete(msg.id)) {
                showTermError(`Sessione terminata (exit ${msg.exit_code})`);
            }
            termSessionId = null;
            attached = false;
            ws.send(JSON.stringify({type: 'term_list'}));
        },
        term_error: (msg) => {
            showTermError(msg.msg);
            if (msg.id && msg.id === termSessionId) {
                document.getElementById('terminal-active').classList.remove('visible');
                document.getElementById('session-picker').style.display = '';
                termSessionId = null;
                attached = false;
                ws.send(JSON.stringify({type: 'term_list'}));
            }
        },
    }));

    function dispatchMessage(msg, conn) {
        if (!msg || typeof msg.type !== 'string') throw new Error('messaggio senza tipo');
        // Map e non oggetto: un `type` come "constructor" non deve trovare i
        // membri di Object.prototype.
        const handler = HANDLERS.get(msg.type);
        if (typeof handler === 'function') {
            handler(msg, conn);
        } else if (msg.type.startsWith('sftp_')) {
            handleFilesMessage(msg);
        }
    }

    function connectServer(ip) {
        const _ip = ip.trim();
        if (!_ip) { alert('Inserire un indirizzo IP valido.'); return; }
        if (!isValidIPv4(_ip) && !isValidHostname(_ip)) {
            alert('Indirizzo non valido.'); return;
        }
        ip = _ip;
        setStatus('connessione...', 'warn');
        certHint.style.display = 'none';
        disconnectHandled = false;
        closeWS();

        const wsUrl = buildWsUrl(ip);
        ws = new WebSocket(wsUrl);
        // I frame dell'output terminale arrivano binari: senza questo il
        // browser li consegnerebbe come Blob, non leggibili in modo sincrono.
        ws.binaryType = 'arraybuffer';

        clearTimeout(connectionTimeout);
        connectionTimeout = setTimeout(() => {
            if (ws.readyState !== WebSocket.OPEN && !disconnectHandled) {
                disconnectHandled = true;
                ws.onclose = null;
                ws.onerror = null;
                ws.close();
                handleDisconnect(ip);
            }
        }, 3000);

        // Stato della sola connessione che sta nascendo: l'indirizzo e l'istante
        // dell'ultimo ping, che serve a calcolare l'RTT quando torna il pong.
        const conn = { ip, pingTimestamp: 0 };

        ws.onopen = () => {
            clearTimeout(connectionTimeout);
            disconnectHandled = false;
            reconnectAttempts = 0;

            // Connessione remota (pagina via HTTPS → wss): PIN obbligatorio.
            if (wsUrl.startsWith('wss://')) {
                sendAuth();
                return; // wait for auth_ok before marking connected
            }
            onAuthenticated(conn);
        };

        ws.onmessage = (e) => {
            // L'output del terminale arriva come frame binario grezzo:
            // niente base64 (~33% di banda) e niente decodifica per byte.
            // Tutto il resto resta JSON.
            if (typeof e.data !== 'string') { handleBinaryFrame(e.data); return; }
            let msg = null;
            try {
                msg = JSON.parse(e.data);
                dispatchMessage(msg, conn);
            } catch (err) {
                // Un messaggio malformato o un gestore che lancia non devono
                // fermare il socket, ma nemmeno sparire: prima il catch vuoto
                // nascondeva anche gli errori di programmazione.
                console.error('liquidmouse: messaggio non gestito',
                              msg && msg.type, err);
            }
        };
        ws.onerror = () => {
            clearTimeout(connectionTimeout);
            // Suggerisce di accettare il certificato se connessione remota fallisce
            if (wsUrl.startsWith('wss://') && reconnectAttempts === 0) {
                // La porta della pagina, non 8443 fissa: se il modem ha
                // rifiutato la 8443 il QR punta a una porta di riserva.
                const httpsUrl = `https://${ip.trim()}:${window.location.port || '8443'}`;
                certLink.textContent = httpsUrl;
                certLink.onclick = () => window.open(httpsUrl, '_blank');
                certHint.style.display = 'block';
            }
        };
        ws.onclose = () => {
            clearTimeout(connectionTimeout);
            clearInterval(pingInterval);
            attached = false;
            if (!disconnectHandled) {
                disconnectHandled = true;
                handleDisconnect(ip);
            }
        };
    }

    // Errore di autenticazione: niente riconnessione automatica. Riprovare
    // da solo manderebbe lo stesso PIN sbagliato fino a MAX_RECONNECTS volte,
    // e al quinto fallimento il server blocca l'IP per 30 minuti: un solo
    // errore di battitura bastava a chiudersi fuori.
    function stopWithError(text) {
        disconnectHandled = true;
        clearTimeout(connectionTimeout);
        closeWS();
        resetLocks();
        setStatus(text, 'err');
        mostraConfig();
    }

    function mostraConfig() {
        if (!configPanel.classList.contains('hidden')) return;
        configPanel.classList.remove('hidden');
        const contenuto = configPanel.querySelector('.config-content');
        anima(configPanel, { opacity: [0, 1] }, RAPIDA);
        if (!anima(contenuto, { opacity: [0, 1], y: [14, 0] }, MOLLA)) pulisciStile(contenuto);
    }

    function handleDisconnect(ip) {
        resetLocks();
        if (reconnectAttempts < MAX_RECONNECTS) {
            reconnectAttempts++;
            const delay = Math.min(1500 * Math.pow(1.5, reconnectAttempts - 1), 15000);
            setStatus(`riconnessione (${reconnectAttempts}/${MAX_RECONNECTS})...`, 'warn');
            setTimeout(() => connectServer(ip), delay);
        } else {
            setStatus('disconnesso', 'err');
            mostraConfig();
        }
    }

    connectBtn.addEventListener('click', () => { authGate.reset(); reconnectAttempts = 0; connectServer(ipInput.value); });
    ipInput.addEventListener('keyup', (e) => { if (e.key === 'Enter') { authGate.reset(); reconnectAttempts = 0; connectServer(ipInput.value); } });
    // Un PIN corretto a mano è un nuovo tentativo deliberato.
    pinInput.addEventListener('input', () => authGate.reset());

    // Gestisce il risveglio dello smartphone (sleep/wake)
    // Forza sempre la riconnessione: dopo sleep la WebSocket può risultare
    // OPEN ma essere in realtà morta (stale), quindi chiudiamo e ricreiamo.
    // Non dopo un errore di PIN (authGate): rimanderebbe lo stesso PIN.
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && authGate.canAutoReconnect()) {
            const ipToConnect = ipInput.value || loadIP();
            if (ipToConnect) {
                reconnectAttempts = 0;
                closeWS();
                connectServer(ipToConnect);
            }
        }
    });

    // Avvio Iniziale Stabile per le WebView
    window.addEventListener('load', () => {
        setTimeout(() => {
            // Auto-fill del PIN da #pin=... (o ?pin=... dei QR vecchi)
            const urlParams = new URLSearchParams(window.location.search);
            const urlPin = pinFromUrl(window.location.href);
            if (urlPin.pin) {
                pinInput.value = urlPin.pin;
                savePIN(urlPin.pin);
                try {
                    history.replaceState(null, '', urlPin.clean);
                } catch (_) {}
            } else {
                pinInput.value = loadPIN();
            }

            // Deep-link finestra PC: ?term=<id> aggancia quella sessione dopo auth.
            pendingTermId = urlParams.get('term');

            const savedIP = loadIP();
            const currentHostname = window.location.hostname;

            let shouldConnectIP = null;
            if (currentHostname === 'localhost' || currentHostname === '127.0.0.1') {
                // Finestra terminale sul PC: pagina servita in locale → loopback.
                shouldConnectIP = '127.0.0.1';
            } else if (currentHostname && currentHostname !== '') {
                // Pagina servita dal server (LAN http o remoto https): usa l'host.
                shouldConnectIP = currentHostname;
            } else if (savedIP) {
                shouldConnectIP = savedIP;
            }

            if (shouldConnectIP) {
                ipInput.value = shouldConnectIP;
                connectServer(shouldConnectIP);
            } else {
                mostraConfig();
            }
        }, 300); // Ritardo essenziale per iOS/Android QR Scanner
    });

    // --- UTILITA' CONDIVISE dai file seguenti ---
    function mostraBanner(banner) {
        const entra = !banner.classList.contains('visible');
        banner.classList.add('visible');
        if (entra && !anima(banner, { opacity: [0, 1], y: [-6, 0] }, MOLLA)) pulisciStile(banner);
    }

    // "2 attive", "1 salvato": il conteggio a destra dei titoli (vuoto se zero).
    function contaAttive(n, uno, molti) {
        return n ? `${n} ${n === 1 ? uno : molti}` : '';
    }
