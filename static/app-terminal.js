// Liquid Mouse — client, 3/4: terminale (xterm.js, sessioni, barra tasti).
//
// Parte del client diviso in quattro script (vedi app-core.js).
//
// Il formato dei frame binari deve restare allineato a
// liquidmouse/net/frames.py — vedi CLAUDE.md.

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
        mostraBanner(banner);
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
        const { del, add } = diffTastiera(termKbdPrev, val);
        // '' come nel keydown di Backspace e nei test dei tasti: non si
        // passa a 0x7f senza provare cmd e PowerShell su Windows.
        if (del > 0) termSend(''.repeat(del));
        if (add) {
            // Un solo carattere dopo ctrl/alt della barra: ctrl+r, alt+f...
            // Un blocco più lungo (incolla, suggerimento) passa così com'è.
            termSend(add.length === 1 && del === 0 ? withMods(add, null, consumeTermMods()) : add);
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

    // --- SHELL: contratto (estratto ed eseguito da tests con node) ---
    // L'elenco delle shell arriva dal server (`shells` in term_sessions, dalla
    // stessa fonte della whitelist): qui non se ne nomina nessuna. La whitelist
    // del server resta l'autorità; questi controlli evitano solo di proporre o
    // inviare ciò che certamente verrebbe rifiutato.
    const SHELL_DEFAULT = [{ cmd: 'cmd.exe', label: 'cmd' }];
    function parseShells(raw) {
        if (!Array.isArray(raw)) return SHELL_DEFAULT;
        const out = [];
        for (const s of raw) {
            if (s && typeof s.cmd === 'string' && typeof s.label === 'string'
                && /^[A-Za-z0-9._-]{1,32}$/.test(s.cmd)
                && s.label.length > 0 && s.label.length <= 32
                && !out.some(o => o.cmd === s.cmd)) {
                out.push({ cmd: s.cmd, label: s.label });
            }
        }
        return out.length ? out : SHELL_DEFAULT;
    }
    function pickShell(shells, preferred) {
        return shells.some(s => s.cmd === preferred) ? preferred : shells[0].cmd;
    }
    function termCreateMessage(shells, cmd) {
        return shells.some(s => s.cmd === cmd) ? { type: 'term_create', cmd: cmd } : null;
    }
    // --- fine contratto ---

    let termShells = SHELL_DEFAULT;
    let termPendingCmd = '';       // shell richiesta con "avvia", per l'intestazione
    // Ultima shell scelta, ricordata fra una visita e l'altra (solo comodità).
    let termShellChoice = (() => {
        try { return localStorage.getItem('liquidMouseShell') || 'cmd.exe'; }
        catch (_) { return 'cmd.exe'; }
    })();

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
                    anima(closeBtn, { scale: [0.88, 1] }, MOLLA);
                    annulla = setTimeout(() => {
                        closeBtn.classList.remove('confirm');
                        closeBtn.textContent = '×';
                    }, 3000);
                    return;
                }
                clearTimeout(annulla);
                if (!ws || ws.readyState !== WebSocket.OPEN) return;
                closeBtn.disabled = true;
                // In attesa che il PC confermi: la scheda sbiadisce.
                anima(card, { opacity: 0.45 }, RAPIDA);
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
        const newLabel = document.createElement('label');
        newLabel.className = 'session-card-label name-new';
        newLabel.htmlFor = 'shell-select';
        newLabel.textContent = 'nuova sessione // shell';

        // Select nativo: sul telefono apre il selettore del sistema, ed è già
        // accessibile (etichetta, tastiera, screen reader).
        const shellSelect = document.createElement('select');
        shellSelect.id = 'shell-select';
        shellSelect.className = 'shell-select';
        termShells.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.cmd;
            opt.textContent = s.label;
            shellSelect.appendChild(opt);
        });
        shellSelect.value = pickShell(termShells, termShellChoice);
        shellSelect.addEventListener('change', () => { termShellChoice = shellSelect.value; });

        const startBtn = document.createElement('button');
        startBtn.className = 'session-card-btn btn-new';
        startBtn.textContent = 'avvia';
        startBtn.addEventListener('click', () => {
            const msg = termCreateMessage(termShells, shellSelect.value);
            if (!msg || !ws || ws.readyState !== WebSocket.OPEN) return;
            termShellChoice = msg.cmd;
            termPendingCmd = msg.cmd;
            try { localStorage.setItem('liquidMouseShell', msg.cmd); } catch (_) {}
            ws.send(JSON.stringify(msg));
        });

        newCard.appendChild(newLabel);
        newCard.appendChild(shellSelect);
        newCard.appendChild(startBtn);
        list.appendChild(newCard);
        animaElenco(list);
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
        const attivo = document.getElementById('terminal-active');
        const dot = document.getElementById('tab-terminal-dot');
        // Solo opacità: dentro c'è #term-kbd-input, fixed (vedi switchTab).
        if (!attivo.classList.contains('visible')) anima(attivo, { opacity: [0, 1] }, RAPIDA);
        attivo.classList.add('visible');
        if (dot.style.display === 'none')
            anima(dot, { scale: [0, 1] }, { type: 'spring', bounce: 0.5, visualDuration: 0.3 });
        dot.style.display = 'block';
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
