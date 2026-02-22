/* chat.init.js - versión mínima segura
   Solo inicializa GLightbox y FgEmojiPicker cuando existen.
   Evita ReferenceError si las librerías no están cargadas.
*/
(function(){
    'use strict';

    // Inicializar GLightbox si está disponible
    try{
        if (typeof window !== 'undefined' && typeof window.GLightbox !== 'undefined'){
            try{ GLightbox({ selector: '.popup-img', title: false }); }
            catch(err){ console.warn('GLightbox init error:', err); }
        }
    }catch(e){ console.warn('GLightbox guard failed', e); }

    // Inicializar FgEmojiPicker si está disponible; ocultar botón si no
    try{
        var emojiBtn = document.getElementById('emoji-btn');
        if (typeof window !== 'undefined' && typeof window.FgEmojiPicker !== 'undefined'){
            try{
                new FgEmojiPicker({
                    trigger: ['.emoji-btn'],
                    removeOnSelection: false,
                    closeButton: true,
                    position: ['top','right'],
                    preFetch: true
                });
            }catch(err){ console.warn('FgEmojiPicker init error:', err); if (emojiBtn) emojiBtn.style.display='none'; }
        } else {
            if (emojiBtn) { emojiBtn.style.display = 'none'; emojiBtn.setAttribute('aria-hidden','true'); }
        }
    }catch(e){ console.warn('FgEmojiPicker guard failed', e); }

    // Chat WS integration (minimal)
    try {
        var usersChat = document.getElementById('users-chat');
        var convId = usersChat && usersChat.getAttribute('data-conversation-id') ? usersChat.getAttribute('data-conversation-id') : '';
        var currentUsername = usersChat && usersChat.getAttribute('data-current-username') ? usersChat.getAttribute('data-current-username') : '';
        if (convId) {
            var wsProtocol = (location.protocol === 'https:') ? 'wss:' : 'ws:';
            var wsUrl = wsProtocol + '//' + location.host + '/ws/chat/' + encodeURIComponent(convId) + '/';
            var socket = null;
            var reconnectAttempts = 0;
            var connected = false;

            function connectSocket(){
                socket = new WebSocket(wsUrl);
                socket.addEventListener('open', function(){
                    connected = true;
                    reconnectAttempts = 0;
                });
                socket.addEventListener('message', function(e){
                    try{
                        var data = JSON.parse(e.data);
                    }catch(err){ return; }
                    if(!data || !data.content) return;
                    renderMessage(data);
                });
                socket.addEventListener('close', function(){
                    connected = false;
                    reconnectAttempts++;
                    var delays = [1000, 3000, 5000, 10000];
                    var idx = Math.min(Math.max(reconnectAttempts-1,0), delays.length-1);
                    var delay = delays[idx];
                    setTimeout(function(){
                        var stillConv = usersChat && usersChat.getAttribute('data-conversation-id');
                        if(stillConv === convId){ connectSocket(); }
                    }, delay);
                });
                socket.addEventListener('error', function(){
                    try{ socket.close(); }catch(e){}
                });
            }

            function renderMessage(payload){
                var container = document.getElementById('users-conversation');
                if(!container) return;
                var last = container.querySelector('li.chat-list');
                var li;
                if(last){
                    li = last.cloneNode(true);
                    li.className = li.className.replace(/\bright\b|\bleft\b/g,'').trim();
                } else {
                    li = document.createElement('li');
                    li.className = 'chat-list';
                    var conv = document.createElement('div'); conv.className='conversation-list';
                    var contentWrap = document.createElement('div'); contentWrap.className='user-chat-content';
                    var ctext = document.createElement('div'); ctext.className='ctext-wrap';
                    var ctextContent = document.createElement('div'); ctextContent.className='ctext-wrap-content';
                    var p = document.createElement('p'); p.className='mb-0';
                    var time = document.createElement('p'); time.className='chat-time mb-0';
                    var small = document.createElement('small');
                    time.appendChild(small);
                    ctextContent.appendChild(p);
                    ctextContent.appendChild(time);
                    ctext.appendChild(ctextContent);
                    contentWrap.appendChild(ctext);
                    conv.appendChild(contentWrap);
                    li.appendChild(conv);
                }
                var contentEl = li.querySelector('.ctext-wrap-content p.mb-0') || li.querySelector('.ctext-wrap-content p');
                if(contentEl) contentEl.textContent = payload.content || '';
                var timeEl = li.querySelector('.chat-time small');
                if(timeEl){
                    var d = new Date();
                    var hh = ('0'+d.getHours()).slice(-2);
                    var mm = ('0'+d.getMinutes()).slice(-2);
                    timeEl.textContent = hh+':'+mm;
                }
                if(payload.sender_username && currentUsername && payload.sender_username === currentUsername){
                    li.classList.add('right');
                } else {
                    li.classList.add('left');
                }
                container.appendChild(li);
                try{
                    var conversation = document.getElementById('chat-conversation');
                    if(conversation) conversation.scrollTop = conversation.scrollHeight;
                }catch(err){}
            }

            var form = document.getElementById('chatinput-form');
            var input = document.getElementById('chat-input');
            if(form && input){
                form.addEventListener('submit', function(e){
                    if(connected && socket && socket.readyState === WebSocket.OPEN){
                        e.preventDefault();
                        var text = input.value ? input.value.trim() : '';
                        if(!text) return;
                        try{ socket.send(JSON.stringify({type: 'message', content: text})); }catch(err){}
                        input.value = '';
                    }
                });
            }

            connectSocket();
        }
    } catch(e){ console.warn('Chat WS guard failed', e); }

})();
