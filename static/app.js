// Liquid Mouse — logica del client.
// Estratto da index.html, dove era inline.
//
// Caricato come script classico e NON come modulo: il markup usa attributi
// onclick= inline, che richiedono funzioni globali. Con type="module" tutti
// i bottoni della barra del terminale smetterebbero di funzionare.
//
// Il formato dei frame binari deve restare allineato a
// liquidmouse/net/frames.py — vedi CLAUDE.md.

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

    // Colore della riga di stato: una classe CSS (ok / warn / err) invece di un
    // colore scritto qui, così la palette resta solo in app.css.
    function setStatus(text, kind) {
        statusDiv.textContent = text;
        statusDiv.className = kind || '';
    }

    function loadPIN() { return localStorage.getItem('liquidMousePIN') || ''; }
    function savePIN(p) { if (p) localStorage.setItem('liquidMousePIN', p); }

    // --- TERMINAL STATE ---
    let termSessionId = null;
    let attached = false;          // true quando la sessione è agganciata a questo ws
    let termSessionCmd = '';       // comando della sessione aperta, per l'intestazione
    // Sessioni chiuse con la × da questo telefono: la loro term_closed non è un
    // errore da mostrare nel banner, l'utente l'ha chiesta.
    const chiuseDaQui = new Set();
    let pendingTermId = null;      // deep-link ?term=<id> (finestra terminale sul PC)
    let xterm = null;
    let xtermOpened = false;
    let xtermPendingData = [];
    let xtermPendingBytes = 0;
    let lastSentSize = { cols: 0, rows: 0 };
    let resizeRaf = null;

    // Deve restare allineato a liquidmouse/net/frames.py:
    //   [0x01][len_id: 1 byte][id: len_id byte ASCII][payload grezzo]
    const FRAME_TERM_OUTPUT = 0x01;
    // Tetto sull'output accumulato prima che xterm sia aperto: senza, un
    // comando prolisso avviato dal telefono fa crescere l'array senza
    // limite. Al riaggancio il server rimanda comunque la schermata.
    const PENDING_MAX_BYTES = 65536;

    function handleBinaryFrame(buf) {
        const view = new Uint8Array(buf);
        if (view.length < 2 || view[0] !== FRAME_TERM_OUTPUT) return;
        const idLen = view[1];
        if (idLen === 0 || view.length < 2 + idLen) return;
        let id = '';
        for (let i = 0; i < idLen; i++) id += String.fromCharCode(view[2 + i]);
        if (termSessionId && id !== termSessionId) return;
        // slice() e non subarray(): xterm puo' bufferizzare internamente e
        // non deve condividere la memoria del frame.
        const payload = view.slice(2 + idLen);
        if (xterm && xtermOpened) {
            xterm.write(payload);
            return;
        }
        xtermPendingData.push(payload);
        xtermPendingBytes += payload.length;
        while (xtermPendingBytes > PENDING_MAX_BYTES && xtermPendingData.length > 1) {
            xtermPendingBytes -= xtermPendingData.shift().length;
        }
    }

    function switchTab(name) {
        // La sessione terminal resta attaccata al cambio tab: xterm conserva
        // lo stato e il server continua a inviare output. Niente detach qui
        // (era la causa della duplicazione: re-attach → replay del ring).
        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
        const content = document.getElementById('content-' + name);
        const btn = document.getElementById('tab-' + name);
        if (content) content.classList.add('active');
        if (btn) btn.classList.add('active');
        document.body.classList.toggle('term-open', name === 'terminal');
        if (name === 'terminal') onTerminalTabOpen();
        if (name === 'files') onFilesTabOpen();
    }

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

        let pingTimestamp = 0;

        ws.onopen = () => {
            clearTimeout(connectionTimeout);
            disconnectHandled = false;
            reconnectAttempts = 0;

            // Connessione remota (pagina via HTTPS → wss): PIN obbligatorio.
            const isRemote = wsUrl.startsWith('wss://');
            const pin = pinInput.value.trim() || loadPIN();
            if (isRemote) {
                if (!pin) {
                    stopWithError('pin richiesto');
                    pinInput.focus();
                    return;
                }
                ws.send(JSON.stringify({ type: 'auth', pin }));
                setStatus('autenticazione...', 'warn');
                return; // wait for auth_ok before marking connected
            }
            _onAuthenticated(ip);
        };

        function _onAuthenticated(ip) {
            setStatus('connessione stabilita', 'ok');
            configPanel.classList.add('hidden'); saveIP(ip.trim());
            savePIN(pinInput.value.trim());
            clearInterval(pingInterval);
            pingInterval = setInterval(() => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    pingTimestamp = Date.now();
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

        ws.onmessage = (e) => {
            // L'output del terminale arriva come frame binario grezzo:
            // niente base64 (~33% di banda) e niente decodifica per byte.
            // Tutto il resto resta JSON.
            if (typeof e.data !== 'string') { handleBinaryFrame(e.data); return; }
            try {
                const msg = JSON.parse(e.data);
                if (msg.type === 'auth_ok') {
                    _onAuthenticated(ip);
                    return;
                } else if (msg.type === 'auth_fail') {
                    const rem = msg.remaining > 0 ? ` (${msg.remaining} tentativi rimasti)` : '';
                    stopWithError(`pin errato${rem}`);
                    return;
                } else if (msg.type === 'auth_blocked') {
                    stopWithError('bloccato — riprova tra 30 min');
                    return;
                } else if (msg.type === 'pong' && pingTimestamp > 0) {
                    const rtt = Date.now() - pingTimestamp;
                    setStatus(`connesso ${rtt}ms`, rtt < 50 ? 'ok' : rtt < 150 ? 'warn' : 'err');
                } else if (msg.type === 'term_sessions') {
                    renderSessionPicker(msg.sessions);
                } else if (msg.type === 'term_created') {
                    termSessionId = msg.id;
                    termSessionCmd = 'cmd.exe';
                    attachSession(msg.id);
                } else if (msg.type === 'term_closed') {
                    // NB: qui siamo in una catena if/else dentro una funzione, non in un
                    // loop: un `break` è SyntaxError e uccide l'intero script della pagina
                    // (bug v2.2.x: client morto su "In attesa..." su tutti i browser)
                    if (msg.id && msg.id !== termSessionId) return;
                    document.getElementById('tab-terminal-dot').style.display = 'none';
                    document.getElementById('terminal-active').classList.remove('visible');
                    document.getElementById('session-picker').style.display = '';
                    if (chiuseDaQui.delete(msg.id)) {
                        // Chiusa con la ×: niente banner d'errore.
                    } else {
                        showTermError(`Sessione terminata (exit ${msg.exit_code})`);
                    }
                    termSessionId = null;
                    attached = false;
                    ws.send(JSON.stringify({type: 'term_list'}));
                } else if (msg.type === 'term_error') {
                    showTermError(msg.msg);
                    if (msg.id && msg.id === termSessionId) {
                        document.getElementById('terminal-active').classList.remove('visible');
                        document.getElementById('session-picker').style.display = '';
                        termSessionId = null;
                        attached = false;
                        ws.send(JSON.stringify({type: 'term_list'}));
                    }
                } else if (msg.type.startsWith('sftp_')) {
                    handleFilesMessage(msg);
                }
            } catch (_) {}
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
        configPanel.classList.remove('hidden');
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
            configPanel.classList.remove('hidden');
        }
    }

    connectBtn.addEventListener('click', () => { reconnectAttempts = 0; connectServer(ipInput.value); });
    ipInput.addEventListener('keyup', (e) => { if (e.key === 'Enter') { reconnectAttempts = 0; connectServer(ipInput.value); } });

    // Gestisce il risveglio dello smartphone (sleep/wake)
    // Forza sempre la riconnessione: dopo sleep la WebSocket può risultare
    // OPEN ma essere in realtà morta (stale), quindi chiudiamo e ricreiamo
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
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
            // Auto-fill PIN from URL ?pin=... parameter
            const urlParams = new URLSearchParams(window.location.search);
            const urlPin = urlParams.get('pin');
            if (urlPin) {
                pinInput.value = urlPin;
                savePIN(urlPin);
                try {
                    const cleanUrl = new URL(window.location.href);
                    cleanUrl.searchParams.delete('pin');
                    history.replaceState(null, '', cleanUrl.toString());
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
                configPanel.classList.remove('hidden');
            }
        }, 300); // Ritardo essenziale per iOS/Android QR Scanner
    });

    // --- SENSIBILITA' CURSORE ---
    // Valore salvato in localStorage, applicato lato client prima dell'invio
    // Valore da localStorage non fidato: vuoto, NaN o fuori scala (una versione
    // vecchia, un salvataggio corrotto) lascerebbe il cursore fermo o impazzito.
    const SENS_MIN = 0.5, SENS_MAX = 4.0, SENS_DEFAULT = 1.8;
    let sensitivity = parseFloat(localStorage.getItem('lm_sensitivity'));
    if (!(sensitivity >= SENS_MIN && sensitivity <= SENS_MAX)) sensitivity = SENS_DEFAULT;

    // --- MOVIMENTO CURSORE ---
    let moveX = 0, moveY = 0, isMoving = false;
    // Resto sub-pixel non ancora spedito, in unita' gia' moltiplicate per
    // la sensibilita'. Vale sempre meno di un pixel per asse.
    let pendingX = 0, pendingY = 0;
    let twoFingerScrollAcc = 0;

    // Invio coalescizzato una volta per frame, ma schedulato SOLO quando c'è
    // input pendente. Da fermo non gira alcun loop a 60fps → meno CPU/batteria
    // sul telefono e nessun risveglio inutile. Comportamento identico in movimento.
    let sendScheduled = false;
    function flushSend() {
        sendScheduled = false;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (isMoving && (moveX !== 0 || moveY !== 0)) {
            // Il resto dell'arrotondamento va conservato, non buttato via
            // (lo scroll qui sotto lo fa gia'). Prima, con il dito lento,
            // moveX*sensitivity valeva p.es. 0.4, arrotondava a 0 e quel 0.4
            // spariva: il cursore non si muoveva finche' non si accelerava.
            // L'accumulatore e' gia' in unita' di output, cosi' non serve
            // ridividere per sensitivity (che da localStorage potrebbe
            // arrivare 0 o NaN).
            pendingX += moveX * sensitivity;
            pendingY += moveY * sensitivity;
            moveX = 0; moveY = 0; isMoving = false;
            const sx = Math.round(pendingX), sy = Math.round(pendingY);
            if (sx !== 0 || sy !== 0) {
                ws.send(JSON.stringify({ type: 'move', x: sx, y: sy }));
                pendingX -= sx; pendingY -= sy;
            }
        }
        if (Math.abs(twoFingerScrollAcc) >= 1) {
            const amount = Math.round(twoFingerScrollAcc / 1.5);
            if (amount !== 0) {
                ws.send(JSON.stringify({ type: 'scroll', amount: amount }));
                twoFingerScrollAcc -= amount * 1.5;
            }
        }
    }
    function scheduleSend() {
        if (!sendScheduled) { sendScheduled = true; requestAnimationFrame(flushSend); }
    }

    const pad = document.getElementById('touchpad');
    let lastX = 0, lastY = 0, touchActive = false;
    let twoFingerLastY = 0;

    // --- GESTURE: TAP-TO-CLICK, DOUBLE-TAP, LONG-PRESS ---
    const TAP_MAX_MS   = 200;
    const TAP_MAX_MOVE = 10;
    const LONG_PRESS_MS = 650;

    let tapStartTime = 0, tapStartX = 0, tapStartY = 0;
    let tapMoved = false, longPressTimer = null;

    pad.addEventListener('touchstart', (e) => {
        e.preventDefault();

        if (e.touches.length === 2) {
            // Due dita: prepara scroll, disabilita movimento cursore
            twoFingerLastY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
            touchActive = false;
            clearTimeout(longPressTimer);
            tapStartTime = 0;
            return;
        }

        touchActive = true;
        lastX = e.touches[0].clientX;
        lastY = e.touches[0].clientY;
        moveX = 0; moveY = 0;

        tapStartTime = Date.now();
        tapStartX = lastX;
        tapStartY = lastY;
        tapMoved = false;

        longPressTimer = setTimeout(() => {
            if (!tapMoved) {
                sendClick('right');
                if (navigator.vibrate) navigator.vibrate(60);
                tapStartTime = 0; // evita tap-to-click dopo long press
            }
        }, LONG_PRESS_MS);
    }, { passive: false });

    pad.addEventListener('touchmove', (e) => {
        e.preventDefault();

        if (e.touches.length === 2) {
            const midY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
            twoFingerScrollAcc += (midY - twoFingerLastY) * 0.375;
            twoFingerLastY = midY;
            scheduleSend();
            return;
        }

        if (!touchActive) return;
        const cx = e.touches[0].clientX, cy = e.touches[0].clientY;

        if (Math.abs(cx - tapStartX) > TAP_MAX_MOVE || Math.abs(cy - tapStartY) > TAP_MAX_MOVE) {
            tapMoved = true;
            clearTimeout(longPressTimer);
        }

        moveX += (cx - lastX); moveY += (cy - lastY);
        isMoving = true; lastX = cx; lastY = cy;
        scheduleSend();
    }, { passive: false });

    pad.addEventListener('touchend', () => {
        touchActive = false;
        clearTimeout(longPressTimer);

        const duration = Date.now() - tapStartTime;
        if (duration < TAP_MAX_MS && !tapMoved && tapStartTime > 0) {
            // Tap rapido = click sinistro (il doppio tap produce due click = double-click OS)
            sendClick('left');
        }
        tapStartTime = 0;
    }, { passive: false });

    pad.addEventListener('touchcancel', () => {
        touchActive = false;
        clearTimeout(longPressTimer);
        tapStartTime = 0;
    }, { passive: false });

    // --- CLICK ---
    const sendClick = (btn) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'click', btn: btn }));
    };

    // --- MENU E LOCKS ---
    const btnMenu = document.getElementById('btn-menu');
    const menuOverlay = document.getElementById('menu-overlay');

    // Stati Tasti Lock
    let locks = { drag: false, ctrl: false, shift: false };

    function resetLocks() {
        locks = { drag: false, ctrl: false, shift: false };
        // Anche il bottone del menu: con trascina attivo resta ambra, e dopo
        // una disconnessione segnalava un trascinamento che il server ha già
        // rilasciato.
        btnMenu.classList.remove('lock-active');
        updateLockUI('btn-drag', false);
        updateLockUI('btn-ctrl', false);
        updateLockUI('btn-shift', false);
    }

    function toggleLock(key, btnId) {
        locks[key] = !locks[key];
        const isActive = locks[key];
        updateLockUI(btnId, isActive);

        if (navigator.vibrate) navigator.vibrate(50);

        if (ws && ws.readyState === WebSocket.OPEN) {
            if (key === 'drag') {
                ws.send(JSON.stringify({ type: 'drag', state: isActive ? 'down' : 'up' }));
                // Feedback visivo sul bottone menu principale se drag è attivo
                if (isActive) btnMenu.classList.add('lock-active'); else btnMenu.classList.remove('lock-active');
            } else {
                ws.send(JSON.stringify({ type: 'key_toggle', key: key, state: isActive ? 'down' : 'up' }));
            }
        }
        // Meglio chiudere sempre per pulizia, l'utente vede lo stato dal bottone.
        closeMenu();
    }

    function updateLockUI(id, active) {
        const el = document.getElementById(id);
        if (active) el.classList.add('lock-active'); else el.classList.remove('lock-active');
    }

    btnMenu.addEventListener('click', () => menuOverlay.classList.add('visible'));
    menuOverlay.addEventListener('click', (e) => {
        if (e.target === menuOverlay) menuOverlay.classList.remove('visible');
    });
    function closeMenu() { menuOverlay.classList.remove('visible'); }

    // Helper: registra touchend (no 300ms delay iOS) con fallback click per mouse/desktop.
    // e.preventDefault() su touchend impedisce il click sintetico successivo.
    function addMenuTap(id, handler) {
        const el = document.getElementById(id);
        let moved = false;
        el.addEventListener('touchstart', () => { moved = false; }, { passive: true });
        el.addEventListener('touchmove',  () => { moved = true;  }, { passive: true });
        el.addEventListener('touchend', (e) => {
            if (!moved) { e.preventDefault(); handler(); }
        });
        el.addEventListener('click', handler); // fallback desktop/mouse
    }

    const send = (msg) => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    };

    // Gestione Bottoni Menu
    addMenuTap('btn-drag',  () => toggleLock('drag',  'btn-drag'));
    addMenuTap('btn-ctrl',  () => toggleLock('ctrl',  'btn-ctrl'));
    addMenuTap('btn-shift', () => toggleLock('shift', 'btn-shift'));

    addMenuTap('btn-esc', () => {
        send({ type: 'key', key: 'esc' });
        updateTextDisplay('esc'); closeMenu();
    });

    addMenuTap('btn-copy', () => {
        send({ type: 'hotkey', keys: ['ctrl', 'c'] });
        updateTextDisplay('copia'); closeMenu();
    });

    addMenuTap('btn-paste', () => {
        send({ type: 'hotkey', keys: ['ctrl', 'v'] });
        updateTextDisplay('incolla'); closeMenu();
    });

    addMenuTap('btn-select-all', () => {
        send({ type: 'hotkey', keys: ['ctrl', 'a'] });
        updateTextDisplay('seleziona tutto'); closeMenu();
    });

    addMenuTap('btn-win', () => {
        send({ type: 'key', key: 'win' });
        updateTextDisplay('win'); closeMenu();
    });

    addMenuTap('btn-media-play', () => {
        send({ type: 'key', key: 'media_play_pause' });
        closeMenu();
    });

    addMenuTap('btn-winv', () => {
        send({ type: 'hotkey', keys: ['win', 'v'] });
        updateTextDisplay('win+v'); closeMenu();
    });

    // --- SLIDER SENSIBILITA' ---
    const sensSlider = document.getElementById('sensitivity-slider');
    const sensValue  = document.getElementById('sens-value');
    sensSlider.value = sensitivity;
    sensValue.textContent = sensitivity.toFixed(1) + 'x';
    sensSlider.addEventListener('input', () => {
        sensitivity = parseFloat(sensSlider.value);
        sensValue.textContent = sensitivity.toFixed(1) + 'x';
        localStorage.setItem('lm_sensitivity', sensitivity);
    });

    // --- DISPLAY TESTO & TASTIERA ---
    const textDisplay = document.getElementById('text-display');
    let displayedText = ''; let displayTimeout;
    let previousValue = '';

    function updateTextDisplay(char) {
        displayedText = (char.length > 1) ? char : (char === '⌫' ? displayedText.slice(0, -1) : (char === '↵' ? displayedText + '\n' : displayedText + char));
        textDisplay.textContent = displayedText;
        textDisplay.classList.add('active');
        clearTimeout(displayTimeout);
        displayTimeout = setTimeout(() => { textDisplay.classList.remove('active'); displayedText = ''; }, 3000);
    }

    addMenuTap('btn-keyboard', () => {
        hiddenInput.value = '';
        previousValue = ''; // Reset essenziale: evita ghost input al riavvio della tastiera
        hiddenInput.focus();
        closeMenu();
    });
    hiddenInput.addEventListener('input', (e) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        const val = hiddenInput.value;
        if (val.length > previousValue.length) {
            const added = val.substring(previousValue.length);
            ws.send(JSON.stringify({ type: 'text', char: added })); updateTextDisplay(added);
        } else if (val.length < previousValue.length) {
            const del = previousValue.length - val.length;
            // Un solo messaggio con il conteggio, non uno per carattere.
            // Prima il server scartava tutti i backspace successivi al
            // primo per via del debounce anti-autorepeat da 80ms: cancellare
            // cinque caratteri ne cancellava uno solo.
            ws.send(JSON.stringify({ type: 'key', key: 'backspace', count: del }));
            updateTextDisplay('⌫'.repeat(Math.min(del, 8)));
        }
        previousValue = val;
    });

    hiddenInput.addEventListener('keydown', (e) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (e.key === 'Enter') {
            e.preventDefault(); ws.send(JSON.stringify({ type: 'key', key: 'enter' }));
            updateTextDisplay('↵'); previousValue = ''; hiddenInput.value = '';
        } else if (e.key === 'Backspace') {
            if (hiddenInput.value.length === 0) {
                // Campo vuoto: 'input' non scatta, invia backspace manualmente
                ws.send(JSON.stringify({ type: 'key', key: 'backspace' })); updateTextDisplay('⌫');
            }
            // Campo non vuoto: l'evento 'input' gestisce la cancellazione
        }
    });

    // --- EFFETTI TOUCH UI ---
    ['btn-menu', 'touchpad'].forEach(id => {
        const el = document.getElementById(id);
        el.addEventListener('touchstart', () => el.classList.add('fluid-pressed'), { passive: true });
        el.addEventListener('touchend', () => el.classList.remove('fluid-pressed'), { passive: true });
    });
    document.querySelectorAll('.menu-btn-item').forEach(el => {
        el.addEventListener('touchstart',  () => el.classList.add('fluid-pressed'),    { passive: true });
        el.addEventListener('touchend',    () => el.classList.remove('fluid-pressed'), { passive: true });
        el.addEventListener('touchcancel', () => el.classList.remove('fluid-pressed'), { passive: true });
    });

    // --- TERMINAL MODE: xterm.js primary, fit-to-viewport, mobile keyboard ---
    const TERM_FONT_FAMILY = 'Menlo, Consolas, "Courier New", monospace';
    let termFontSz = parseInt(localStorage.getItem('termFontSize') || '11', 10);

    // Misura char metrics tramite span hidden (no FitAddon).
    function measureCharSize() {
        const span = document.createElement('span');
        span.style.cssText = `visibility:hidden;position:absolute;left:-9999px;` +
            `font-family:${TERM_FONT_FAMILY};font-size:${termFontSz}px;white-space:pre;line-height:1.2;`;
        span.textContent = 'M'.repeat(100);
        document.body.appendChild(span);
        const rect = span.getBoundingClientRect();
        document.body.removeChild(span);
        return { w: rect.width / 100, h: rect.height };
    }

    function initXterm() {
        if (xterm) return;
        xterm = new Terminal({
            cols: 80, rows: 24,
            // Tema cyber (app.css :root). Verde, blu, magenta e ciano non
            // esistono nella palette di PiDash: sono toni caldi e smorzati
            // scelti per restare distinguibili sul fondo #1d1815.
            theme: {
                background: '#1d1815',
                foreground: '#eee4cd',
                cursor: '#f2bb5b',
                cursorAccent: '#1d1815',
                selectionBackground: 'rgba(242,187,91,0.35)',
                black: '#2a2320', red: '#ec5c66', green: '#a9c47f', yellow: '#f2bb5b',
                blue: '#8fa9c9', magenta: '#d38fae', cyan: '#8cc5b7', white: '#eee4cd',
                brightBlack: '#a59b8c', brightRed: '#f28a90', brightGreen: '#c3d9a0',
                brightYellow: '#f6d08a', brightBlue: '#b1c5dd', brightMagenta: '#e3b2c8',
                brightCyan: '#b0d9cf', brightWhite: '#f6efdf',
            },
            fontSize: termFontSz,
            fontFamily: TERM_FONT_FAMILY,
            scrollback: 5000,
            cursorBlink: true,
            convertEol: false,
            allowProposedApi: true,
        });
        xterm.onData(data => {
            if (ws && ws.readyState === WebSocket.OPEN && termSessionId) {
                ws.send(JSON.stringify({type:'term_input', id: termSessionId, data}));
            }
        });
    }

    function openXtermIfNeeded() {
        if (xtermOpened || !xterm) return;
        xterm.open(document.getElementById('xterm-container'));
        xtermOpened = true;
        xtermPendingData.forEach(bytes => xterm.write(bytes));
        xtermPendingData = []; xtermPendingBytes = 0;
        // Primo fit dopo che layout è stabile.
        requestAnimationFrame(() => requestAnimationFrame(fitXterm));
    }

    // Dimensioni reali di cella lette da xterm (più accurate della misura
    // manuale → wrapping corretto); fallback a measureCharSize() se l'API
    // interna non è ancora disponibile (primo render).
    function getCellSize() {
        try {
            const d = xterm._core._renderService.dimensions;
            const cw = d.css.cell.width, ch = d.css.cell.height;
            if (cw > 0 && ch > 0) return { w: cw, h: ch };
        } catch (_) {}
        return measureCharSize();
    }

    function fitXterm() {
        if (!xterm || !xtermOpened) return;
        const container = document.getElementById('xterm-container');
        const w = container.clientWidth - 8;
        const h = container.clientHeight - 8;
        if (w <= 0 || h <= 0) return;
        const { w: cw, h: ch } = getCellSize();
        const cols = Math.max(20, Math.floor(w / cw));
        const rows = Math.max(5, Math.floor(h / ch));
        if (cols !== lastSentSize.cols || rows !== lastSentSize.rows) {
            try { xterm.resize(cols, rows); } catch (_) {}
            if (ws && ws.readyState === WebSocket.OPEN && termSessionId) {
                ws.send(JSON.stringify({type: 'term_resize', id: termSessionId, cols, rows}));
            }
            lastSentSize = { cols, rows };
        }
    }

    function scheduleFit() {
        if (resizeRaf) cancelAnimationFrame(resizeRaf);
        resizeRaf = requestAnimationFrame(fitXterm);
    }

    window.addEventListener('resize', scheduleFit);
    window.addEventListener('orientationchange', () => setTimeout(scheduleFit, 200));

    // --- TASTIERA DEL TELEFONO: pagina ridotta all'area visibile ---
    // La tastiera copre la pagina senza ridurne l'altezza (Safari sempre,
    // Chrome Android senza interactive-widget): la riga del cursore e la barra
    // tasti finivano sotto. visualViewport misura l'area davvero visibile e il
    // body (app.css) la segue; il terminale poi si ridimensiona sulle righe
    // rimaste e torna in fondo, dove c'è il cursore.
    const vv = window.visualViewport;
    let vvFullH = { w: 0, h: 0 };   // altezza a tastiera chiusa, per larghezza
    let kbdOpen = false;
    function syncViewport() {
        if (!vv || Math.abs(vv.scale - 1) > 0.01) return;
        const root = document.documentElement.style;
        root.setProperty('--vv-h', `${Math.round(vv.height)}px`);
        root.setProperty('--vv-top', `${Math.round(vv.offsetTop)}px`);
        // Tastiera aperta = altezza visibile ben sotto quella a tastiera
        // chiusa. innerHeight non basta: con resizes-content si accorcia anche
        // lui. Il massimo si azzera quando cambia la larghezza (rotazione).
        if (vvFullH.w !== vv.width) vvFullH = { w: vv.width, h: 0 };
        vvFullH.h = Math.max(vvFullH.h, vv.height, window.innerHeight);
        const aperta = vv.height < vvFullH.h * 0.8;
        if (aperta !== kbdOpen) {
            kbdOpen = aperta;
            document.body.classList.toggle('kbd-open', aperta);
        }
        scheduleFit();
        // Dopo il ridimensionamento il cursore deve restare in vista: xterm
        // non scorre da solo quando le righe diminuiscono sotto lo scroll.
        requestAnimationFrame(() => { if (xterm && xtermOpened) xterm.scrollToBottom(); });
    }
    if (vv) {
        vv.addEventListener('resize', syncViewport);
        vv.addEventListener('scroll', syncViewport);
        syncViewport();
    }

    function onTerminalTabOpen() {
        initXterm();
        if (!ws || ws.readyState !== WebSocket.OPEN) {
            showTermError('WebSocket non connesso — connetti prima dalla schermata principale.');
            return;
        }
        const pickerAperto = !document.getElementById('terminal-active').classList.contains('visible');
        if (termSessionId && attached && pickerAperto) {
            // Tornati all'elenco con "‹ sessioni": la sessione resta agganciata
            // (xterm continua a ricevere l'output), ma l'elenco va aggiornato.
            ws.send(JSON.stringify({type: 'term_list'}));
        } else if (termSessionId && attached) {
            // Già agganciata: la sessione è rimasta viva al cambio tab e
            // xterm ha già lo stato aggiornato. Riallinea solo le dimensioni.
            openXtermIfNeeded();
            scheduleFit();
        } else if (termSessionId) {
            attachSession(termSessionId);
        } else {
            ws.send(JSON.stringify({type: 'term_list'}));
        }
    }

    function showTermError(msg) {
        const banner = document.getElementById('term-error-banner');
        banner.textContent = msg;
        banner.classList.add('visible');
        setTimeout(() => banner.classList.remove('visible'), 5000);
    }

    // --- TASTI DEL TERMINALE: contratto (tests/test_term_keys.py) ---
    // Sequenze VT inviate al PTY come term_input: ConPTY e winpty le
    // traducono nei tasti Windows corrispondenti, come fa Windows Terminal.
    const TERM_KEYS = {
        esc: '\x1b', tab: '\t', enter: '\r',
        up: '\x1b[A', down: '\x1b[B', right: '\x1b[C', left: '\x1b[D',
        home: '\x1b[H', end: '\x1b[F', pgup: '\x1b[5~', pgdn: '\x1b[6~',
        'ctrl-c': '\x03', 'ctrl-d': '\x04', 'ctrl-z': '\x1a', 'ctrl-l': '\x0c',
    };
    // Tasti che con un modificatore diventano CSI 1;<mod><finale> (xterm):
    // ctrl+← = parola precedente, ctrl+home = inizio del buffer.
    const CSI_MOD_FINAL = { up: 'A', down: 'B', right: 'C', left: 'D', home: 'H', end: 'F' };

    // Ctrl+carattere come lo produce una tastiera vera: lettere e @[\]^_ →
    // codice di controllo (ctrl+c = 0x03), spazio → NUL. Il resto non cambia.
    function ctrlChar(c) {
        if (c === ' ') return '\x00';
        const code = c.toUpperCase().charCodeAt(0);
        return (code >= 64 && code <= 95) ? String.fromCharCode(code - 64) : c;
    }

    // Applica ctrl/alt a un tasto della barra (`name`) o a un carattere
    // digitato (`name` null). Funzione pura: mods arriva da fuori.
    function withMods(data, name, mods) {
        if (!mods.ctrl && !mods.alt) return data;
        if (name && CSI_MOD_FINAL[name]) {
            const m = 1 + (mods.alt ? 2 : 0) + (mods.ctrl ? 4 : 0);
            return `\x1b[1;${m}${CSI_MOD_FINAL[name]}`;
        }
        let out = data;
        if (mods.ctrl && out.length === 1) out = ctrlChar(out);
        if (mods.alt) out = '\x1b' + out;
        return out;
    }
    // --- fine contratto ---

    function termSend(data) {
        if (ws && ws.readyState === WebSocket.OPEN && termSessionId) {
            ws.send(JSON.stringify({type: 'term_input', id: termSessionId, data}));
            // L'input passa da termKbdInput, non da xterm: senza questo, dopo
            // aver scorso la cronologia si scriveva alla cieca, fuori vista.
            if (xterm && xtermOpened) xterm.scrollToBottom();
        }
    }

    // Ctrl e alt della barra valgono per il tasto successivo (barra o tastiera
    // del telefono), poi si spengono: come sulle tastiere dei terminali mobili.
    const termMods = { ctrl: false, alt: false };
    function setTermMod(name, on) {
        termMods[name] = on;
        document.querySelector(`.tkey[data-key="${name}"]`).classList.toggle('lock-active', on);
    }
    function consumeTermMods() {
        const mods = { ...termMods };
        if (mods.ctrl) setTermMod('ctrl', false);
        if (mods.alt) setTermMod('alt', false);
        return mods;
    }

    function pressTermKey(name) {
        if (name === 'ctrl' || name === 'alt') { setTermMod(name, !termMods[name]); return; }
        const seq = TERM_KEYS[name];
        if (seq !== undefined) termSend(withMods(seq, name, consumeTermMods()));
    }

    const TKEY_REPEAT_DELAY = 400, TKEY_REPEAT_EVERY = 70;
    document.querySelectorAll('.tkey').forEach(el => {
        let delay = null, every = null;
        const stop = () => {
            clearTimeout(delay); clearInterval(every); delay = every = null;
            el.classList.remove('fluid-pressed');
        };
        el.addEventListener('touchstart', (e) => {
            // preventDefault: il tocco non sposta il focus, così la tastiera
            // del telefono resta aperta mentre si usano frecce e scorciatoie.
            e.preventDefault();
            el.classList.add('fluid-pressed');
            pressTermKey(el.dataset.key);
            // Tenere premuto ripete (frecce, pagine): scorrere la cronologia
            // o spostare il cursore senza toccare venti volte.
            if ('repeat' in el.dataset) {
                delay = setTimeout(() => {
                    every = setInterval(() => pressTermKey(el.dataset.key), TKEY_REPEAT_EVERY);
                }, TKEY_REPEAT_DELAY);
            }
        }, { passive: false });
        el.addEventListener('touchend', stop);
        el.addEventListener('touchcancel', stop);
        // Mouse (finestra del terminale sul PC): niente cambio di focus
        // al mousedown, azione al click. Col tocco il click non arriva.
        el.addEventListener('mousedown', (e) => e.preventDefault());
        el.addEventListener('click', () => pressTermKey(el.dataset.key));
    });

    // Tastiera mobile: hidden input, sync ad xterm. Il tap sul terminale
    // stesso porta il focus qui (niente più bottone dedicato) così la
    // tastiera di sistema si apre come su un vero terminale.
    const termKbdInput = document.getElementById('term-kbd-input');
    let termKbdPrev = '';
    document.getElementById('xterm-container').addEventListener('click', () => {
        termKbdInput.value = '';
        termKbdPrev = '';
        termKbdInput.focus();
    });
    termKbdInput.addEventListener('input', () => {
        if (!ws || ws.readyState !== WebSocket.OPEN || !termSessionId) return;
        const val = termKbdInput.value;
        if (val.length > termKbdPrev.length) {
            const added = val.substring(termKbdPrev.length);
            // Un solo carattere dopo ctrl/alt della barra: ctrl+r, alt+f...
            // Un blocco più lungo (incolla, suggerimento) passa così com'è.
            termSend(added.length === 1 ? withMods(added, null, consumeTermMods()) : added);
        } else if (val.length < termKbdPrev.length) {
            termSend('\b'.repeat(termKbdPrev.length - val.length));
        }
        termKbdPrev = val;
    });
    termKbdInput.addEventListener('keydown', e => {
        if (!ws || ws.readyState !== WebSocket.OPEN || !termSessionId) return;
        const frecce = { ArrowUp: 'up', ArrowDown: 'down', ArrowRight: 'right', ArrowLeft: 'left' };
        if (e.key === 'Enter') {
            e.preventDefault();
            termSend('\r');
            termKbdInput.value = ''; termKbdPrev = '';
        } else if (e.key === 'Backspace' && termKbdInput.value.length === 0) {
            termSend('\b');
        } else if (frecce[e.key]) {
            e.preventDefault();
            pressTermKey(frecce[e.key]);
        }
    });

    function renderSessionPicker(sessions) {
        const list = document.getElementById('session-list');
        list.innerHTML = '';
        const alive = sessions.filter(s => s.alive);
        document.getElementById('session-count').textContent = contaAttive(alive.length, 'attiva', 'attive');

        alive.forEach(s => {
            const age = Math.round((Date.now()/1000 - s.created_at) / 60);
            const card = document.createElement('div');
            card.className = 'session-card existing';

            const labelDiv = document.createElement('div');
            labelDiv.className = 'session-card-label';

            const nameDiv = document.createElement('div');
            nameDiv.className = 'name';
            nameDiv.textContent = s.cmd;

            const metaDiv = document.createElement('div');
            metaDiv.className = 'meta';
            metaDiv.textContent = (s.id === termSessionId ? 'aperta qui · ' : '') + `avviata ${age} min fa`;

            labelDiv.appendChild(nameDiv);
            labelDiv.appendChild(metaDiv);

            const resumeBtn = document.createElement('button');
            resumeBtn.className = 'session-card-btn btn-resume';
            resumeBtn.setAttribute('data-id', s.id);
            resumeBtn.textContent = 'riprendi';
            resumeBtn.addEventListener('click', () => {
                termSessionId = s.id;
                termSessionCmd = s.cmd;
                attachSession(s.id);
            });

            // × chiude la sessione (termina la shell sul PC). Il primo tocco
            // chiede conferma, il secondo chiude: un tocco sbagliato in un
            // elenco non deve bastare a perdere un lavoro in corso.
            const closeBtn = document.createElement('button');
            closeBtn.className = 'session-card-close';
            closeBtn.setAttribute('aria-label', `chiudi la sessione ${s.cmd}`);
            closeBtn.textContent = '×';
            let annulla = null;
            closeBtn.addEventListener('click', () => {
                if (!closeBtn.classList.contains('confirm')) {
                    closeBtn.classList.add('confirm');
                    closeBtn.textContent = 'chiudi?';
                    annulla = setTimeout(() => {
                        closeBtn.classList.remove('confirm');
                        closeBtn.textContent = '×';
                    }, 3000);
                    return;
                }
                clearTimeout(annulla);
                if (!ws || ws.readyState !== WebSocket.OPEN) return;
                closeBtn.disabled = true;
                chiuseDaQui.add(s.id);
                ws.send(JSON.stringify({type: 'term_kill', id: s.id}));
            });

            const actions = document.createElement('div');
            actions.className = 'session-card-actions';
            actions.appendChild(resumeBtn);
            actions.appendChild(closeBtn);

            card.appendChild(labelDiv);
            card.appendChild(actions);
            list.appendChild(card);
        });

        const newCard = document.createElement('div');
        newCard.className = 'session-card new-session';
        newCard.innerHTML = `
            <div class="session-card-label">
                <div class="name-new">nuova sessione</div>
            </div>
            <button class="session-card-btn btn-new btn-cmd">cmd</button>`;
        newCard.querySelector('.btn-cmd').addEventListener('click', () => {
            ws.send(JSON.stringify({type: 'term_create', cmd: 'cmd.exe'}));
        });
        list.appendChild(newCard);
    }

    // "‹ sessioni": torna all'elenco senza chiudere né sganciare la sessione,
    // che continua a girare sul PC. Prima, una volta dentro, l'elenco non si
    // rivedeva più finché la shell non usciva da sola.
    function showSessionPicker() {
        document.getElementById('terminal-active').classList.remove('visible');
        document.getElementById('session-picker').style.display = '';
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type: 'term_list'}));
    }
    document.getElementById('term-back').addEventListener('click', showSessionPicker);

    function attachSession(sid) {
        document.getElementById('term-title').textContent = `${termSessionCmd || 'sessione'} · ${sid}`;
        document.getElementById('session-picker').style.display = 'none';
        document.getElementById('terminal-active').classList.add('visible');
        document.getElementById('tab-terminal-dot').style.display = 'block';
        // Il server, su term_attach, re-invia l'intero ring buffer. Azzeriamo
        // xterm PRIMA del replay così lo schermo si ricostruisce senza
        // duplicare l'output (causa storica del "terminal che non si aggiorna").
        xtermPendingData = []; xtermPendingBytes = 0;
        openXtermIfNeeded();
        if (xterm) xterm.reset();
        attached = true;
        ws.send(JSON.stringify({type: 'term_attach', id: sid}));
        // Fit dopo che layout si è assestato
        setTimeout(fitXterm, 50);
        setTimeout(fitXterm, 250);
    }


    // --- FILE MANAGER (SFTP) ---------------------------------------------------
    // Il telefono non parla SSH: chiede al PC (messaggi sftp_*, vedi
    // liquidmouse/net/protocol.py) e trasferisce i file via HTTP con un
    // biglietto monouso (/sftp/dl, /sftp/up). I nomi dei file sono dati
    // esterni: si scrivono sempre con textContent, mai innerHTML.

    // --- FILE: contratto (estratto ed eseguito da tests con node) ---
    function formatSize(n) {
        if (!(n >= 0)) return '';
        const unita = ['B', 'KB', 'MB', 'GB', 'TB'];
        let i = 0;
        while (n >= 1024 && i < unita.length - 1) { n /= 1024; i++; }
        return (i === 0 || n >= 10 ? Math.round(n) : n.toFixed(1)) + ' ' + unita[i];
    }
    function joinPath(folder, name) {
        return (folder === '/' ? '' : folder.replace(/\/+$/, '')) + '/' + name;
    }
    function parentPath(path) {
        const i = path.replace(/\/+$/, '').lastIndexOf('/');
        return i <= 0 ? '/' : path.slice(0, i);
    }
    // --- fine contratto ---

    const filesEl = {
        banner: document.getElementById('files-banner'),
        profiles: document.getElementById('files-profiles'),
        profileList: document.getElementById('files-profile-list'),
        browser: document.getElementById('files-browser'),
        path: document.getElementById('files-path'),
        list: document.getElementById('files-list'),
        progress: document.getElementById('files-progress'),
        input: document.getElementById('files-input'),
    };
    let filesPath = '/';
    let filesConnected = false;
    let uploadQueue = [];
    let uploadBusy = false;
    let uploadDone = false;   // almeno un file è stato caricato: ricarica l'elenco alla fine

    function filesSend(msg) {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    }
    function filesError(text) {
        filesEl.banner.textContent = text;
        filesEl.banner.classList.add('visible');
        clearTimeout(filesError.t);
        filesError.t = setTimeout(() => filesEl.banner.classList.remove('visible'), 6000);
    }
    function filesShow(browser) {
        filesEl.browser.classList.toggle('visible', browser);
        filesEl.profiles.style.display = browser ? 'none' : '';
    }
    function filesReset() {
        filesConnected = false;
        uploadQueue = []; uploadBusy = false;
        filesEl.progress.textContent = '';
        filesShow(false);
    }
    function onFilesTabOpen() {
        if (!filesConnected) filesSend({ type: 'sftp_profiles' });
    }
    function filesList(path) { filesSend({ type: 'sftp_list', path: path }); }

    // Bottone con conferma al secondo tocco, come la × delle sessioni.
    function confirmButton(label, action) {
        const b = document.createElement('button');
        b.className = 'session-card-close';
        b.textContent = label;
        let timer = null;
        b.addEventListener('click', (e) => {
            e.stopPropagation();
            if (b.classList.contains('confirm')) { clearTimeout(timer); action(); return; }
            b.classList.add('confirm');
            b.textContent = 'sicuro?';
            timer = setTimeout(() => { b.classList.remove('confirm'); b.textContent = label; }, 3000);
        });
        return b;
    }

    function renderProfiles(profiles) {
        filesEl.profileList.replaceChildren();
        document.getElementById('files-profile-count').textContent =
            contaAttive(profiles.length, 'salvato', 'salvati');
        profiles.forEach(p => {
            const card = document.createElement('div');
            card.className = 'session-card existing';
            const label = document.createElement('div');
            label.className = 'session-card-label';
            const name = document.createElement('div');
            name.className = 'name'; name.textContent = p.name;
            const meta = document.createElement('div');
            meta.className = 'meta';
            meta.textContent = `${p.user}@${p.host}:${p.port}`;
            label.append(name, meta);
            const actions = document.createElement('div');
            actions.className = 'session-card-actions';
            const go = document.createElement('button');
            go.className = 'session-card-btn btn-resume';
            go.textContent = 'apri';
            go.addEventListener('click', () => {
                go.disabled = true; go.textContent = '...';
                filesSend({ type: 'sftp_connect', name: p.name });
            });
            actions.append(go, confirmButton('×', () =>
                filesSend({ type: 'sftp_profile_delete', name: p.name })));
            card.append(label, actions);
            filesEl.profileList.append(card);
        });
    }

    // "2 attive", "1 salvato": il conteggio a destra dei titoli (vuoto se zero).
    function contaAttive(n, uno, molti) {
        return n ? `${n} ${n === 1 ? uno : molti}` : '';
    }

    // Icona a tratto come quelle del menu (stroke="currentColor"): il glifo ✎
    // non esiste in Space Mono e il telefono lo pescava da un font emoji.
    function iconaSvg(d) {
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.setAttribute('aria-hidden', 'true');
        const path = document.createElementNS(ns, 'path');
        path.setAttribute('d', d);
        svg.append(path);
        return svg;
    }
    const ICONA_MATITA = 'M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z';

    function fmtDate(t) {
        if (!t) return '';
        const d = new Date(t * 1000);
        const p = (n) => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    }

    function renderListing(msg) {
        filesPath = msg.path;
        filesEl.path.textContent = msg.path;
        filesEl.list.replaceChildren();
        if (!msg.entries.length) {
            const e = document.createElement('div');
            e.className = 'file-empty'; e.textContent = 'cartella vuota';
            filesEl.list.append(e);
        }
        msg.entries.forEach(f => {
            const row = document.createElement('div');
            row.className = 'session-card file-row' + (f.dir ? ' is-dir' : '');
            const label = document.createElement('div');
            label.className = 'session-card-label';
            const name = document.createElement('div');
            name.className = 'name';
            if (f.dir) {
                const mark = document.createElement('span');
                mark.className = 'dir-mark';
                mark.setAttribute('aria-hidden', 'true');
                mark.textContent = '▸';
                name.append(mark);
            }
            name.append(f.name);
            const meta = document.createElement('div');
            meta.className = 'meta';
            meta.textContent = [f.dir ? 'cartella' : formatSize(f.size), fmtDate(f.mtime)]
                .filter(Boolean).join(' // ');
            label.append(name, meta);
            row.addEventListener('click', () => {
                if (f.dir) filesList(joinPath(filesPath, f.name));
                else filesSend({ type: 'sftp_ticket', direction: 'dl', path: filesPath, name: f.name });
            });
            const actions = document.createElement('div');
            actions.className = 'session-card-actions';
            const ren = document.createElement('button');
            ren.className = 'session-card-close';
            ren.append(iconaSvg(ICONA_MATITA));
            ren.setAttribute('aria-label', `rinomina ${f.name}`);
            ren.addEventListener('click', (e) => {
                e.stopPropagation();
                const nuovo = prompt('nuovo nome', f.name);
                if (nuovo && nuovo !== f.name)
                    filesSend({ type: 'sftp_rename', path: filesPath, old: f.name, new: nuovo });
            });
            actions.append(ren, confirmButton('×', () =>
                filesSend({ type: 'sftp_delete', path: filesPath, name: f.name, dir: f.dir })));
            row.append(label, actions);
            filesEl.list.append(row);
        });
        if (msg.truncated) {
            const e = document.createElement('div');
            e.className = 'file-empty'; e.textContent = 'elenco troncato';
            filesEl.list.append(e);
        }
    }

    function startDownload(msg) {
        const a = document.createElement('a');
        a.href = '/sftp/dl?t=' + encodeURIComponent(msg.token);
        a.download = msg.name;
        document.body.append(a);
        a.click();
        a.remove();
    }

    // Upload in coda, un file alla volta: ogni file ha il suo biglietto.
    function queueUploads(files) {
        uploadQueue.push(...files);
        if (!uploadBusy) nextUpload();
    }
    function nextUpload(overwrite) {
        const file = uploadQueue[0];
        if (!file) {
            uploadBusy = false;
            filesEl.progress.textContent = '';
            if (uploadDone) { uploadDone = false; filesList(filesPath); }
            return;
        }
        uploadBusy = true;
        filesEl.progress.style.setProperty('--p', '0%');
        filesEl.progress.textContent = `carico ${file.name}...`;
        filesSend({ type: 'sftp_ticket', direction: 'up', path: filesPath,
                    name: file.name, overwrite: overwrite === true });
    }
    function sendUpload(msg) {
        const file = uploadQueue[0];
        if (!file) return;
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/sftp/up?t=' + encodeURIComponent(msg.token));
        xhr.upload.onprogress = (e) => {
            if (!e.lengthComputable) return;
            const pct = Math.round(100 * e.loaded / e.total);
            filesEl.progress.textContent = `carico ${file.name} // ${pct}%`;
            filesEl.progress.style.setProperty('--p', `${pct}%`);
        };
        xhr.onload = () => {
            if (xhr.status === 200) uploadDone = true;
            else filesError(`upload di ${file.name} non riuscito`);
            uploadQueue.shift(); nextUpload();
        };
        xhr.onerror = () => {
            filesError(`upload di ${file.name} interrotto`);
            uploadQueue.shift(); nextUpload();
        };
        xhr.send(file);
    }

    function handleFilesMessage(msg) {
        if (msg.type === 'sftp_profiles') {
            renderProfiles(msg.profiles);
        } else if (msg.type === 'sftp_connected') {
            filesConnected = true;
            filesShow(true);
            filesList(msg.path);
        } else if (msg.type === 'sftp_disconnected') {
            filesReset();
            filesSend({ type: 'sftp_profiles' });
        } else if (msg.type === 'sftp_listing') {
            renderListing(msg);
        } else if (msg.type === 'sftp_ok') {
            filesList(filesPath);
        } else if (msg.type === 'sftp_ticket') {
            if (msg.direction === 'dl') startDownload(msg); else sendUpload(msg);
        } else if (msg.type === 'sftp_error') {
            // Un upload in corso che trova il file già presente chiede conferma;
            // qualunque altro errore lo interrompe e passa al file dopo.
            if (uploadBusy && msg.code === 'exists') {
                if (confirm(`${uploadQueue[0].name} esiste già. sovrascrivere?`)) { nextUpload(true); return; }
                uploadQueue.shift(); nextUpload(); return;
            }
            if (uploadBusy && (msg.code === 'remote_upload' || msg.code === 'disconnected')) {
                uploadQueue = []; uploadBusy = false; filesEl.progress.textContent = '';
            } else if (uploadBusy) {
                uploadQueue.shift(); nextUpload();
            }
            filesError(msg.msg);
            // Un connect fallito lascia il bottone "apri" bloccato: si ridisegna.
            if (!filesConnected) filesSend({ type: 'sftp_profiles' });
        }
    }

    document.getElementById('files-profile-form').addEventListener('submit', (e) => {
        e.preventDefault();
        const v = (id) => document.getElementById(id).value.trim();
        filesSend({ type: 'sftp_profile_save', name: v('pf-name'), host: v('pf-host'),
                    port: parseInt(v('pf-port'), 10) || 22, user: v('pf-user'),
                    password: document.getElementById('pf-pass').value });
        document.getElementById('pf-pass').value = '';
    });
    document.getElementById('files-back').addEventListener('click', () => {
        filesSend({ type: 'sftp_disconnect' });
    });
    document.getElementById('files-up').addEventListener('click', () => filesList(parentPath(filesPath)));
    document.getElementById('files-refresh').addEventListener('click', () => filesList(filesPath));
    document.getElementById('files-mkdir').addEventListener('click', () => {
        const nome = prompt('nome della nuova cartella');
        if (nome) filesSend({ type: 'sftp_mkdir', path: filesPath, name: nome });
    });
    document.getElementById('files-upload').addEventListener('click', () => filesEl.input.click());
    filesEl.input.addEventListener('change', () => {
        queueUploads(Array.from(filesEl.input.files));
        filesEl.input.value = '';
    });
