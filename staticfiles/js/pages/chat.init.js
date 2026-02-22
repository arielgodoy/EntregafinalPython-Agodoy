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

})();
