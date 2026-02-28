(function(){ "use strict";

const DEBUG = true;

function getCookie(name){ const value="; "+document.cookie; const parts=value.split("; "+name+"="); if(parts.length===2) return parts.pop().split(";").shift(); return null; }

function safeJsonParse(s){ try{ return JSON.parse(s);}catch(e){ return null;} }

function nowIso(){ return new Date().toISOString(); }

function escapeHtml(str){ if(str==null) return ""; return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }

// Muestra UI indicando que el sistema de mensajería (WebSocket) no está disponible
function showWsUnavailable(){ try{ var input = document.getElementById("chat-input"); if(input){ input.disabled = true; try{ input.placeholder = "Sistema de mensajería no disponible"; }catch(e){} }
  var root = document.getElementById("chat-root"); if(!root) return; if(document.getElementById('ws-offline-alert')) return; var alert = document.createElement('div'); alert.id = 'ws-offline-alert'; alert.className = 'alert alert-danger mt-2'; alert.textContent = 'Sistema de mensajería no disponible'; root.insertBefore(alert, root.firstChild); }catch(e){} }

// Detecta el contenedor real que debe scrollearse
function findScrollContainer(box, list){ try{
    if(!box && !list) return null;
    if(box){ var inner = box.querySelector('.simplebar-content-wrapper'); if(inner) return inner; }
    if(list && list.closest){ var closest = list.closest('.simplebar-content-wrapper'); if(closest) return closest; }
    if(box && box.scrollHeight > box.clientHeight) return box;
    if(list && list.parentElement && list.parentElement.scrollHeight > list.parentElement.clientHeight) return list.parentElement;
  }catch(e){}
  return box || null;
}

// Hace scroll al fondo usando doble requestAnimationFrame para esperar al layout
function scrollToBottom(el){ if(!el) return; try{ requestAnimationFrame(function(){ requestAnimationFrame(function(){ try{ el.scrollTop = el.scrollHeight; }catch(e){} }); }); }catch(e){} }

// Oculta el spinner de carga del chat si existe
function hideChatSpinner(){ try{
    var el = document.getElementById("chat-loading-spinner")
      || document.querySelector("#chat-loading-spinner")
      || document.querySelector("#elmLoader")
      || document.querySelector(".chat-loading-spinner")
      || document.querySelector(".chat-loader")
      || document.querySelector(".spinner-border")
      || null;
    if(!el) return;
    el.style.display = "none";
    el.setAttribute("aria-hidden","true");
  }catch(e){}
}

function appendMessage(data){
  const box = document.getElementById("chat-conversation") || document.getElementById("chat-messages");
  if(!box) return;
  const list = document.getElementById("users-conversation") || document.getElementById("chat-messages-list") || box.querySelector('#users-conversation');
  if(!list) return;
  const item = document.createElement("li");
  item.className = "chat-list" + (data.is_me?" right":" left");
  item.dataset.messageId = data.id||"";
  const conv = document.createElement("div"); conv.className = "conversation-list";
  const content = document.createElement("div"); content.className = "user-chat-content";
  const wrap = document.createElement("div"); wrap.className = "ctext-wrap";
  const wrapContent = document.createElement("div"); wrapContent.className = "ctext-wrap-content";
  const p = document.createElement("p"); p.className = "mb-0"; p.innerHTML = escapeHtml(data.text||"");
  const meta = document.createElement("p"); meta.className = "chat-time mb-0";
  const small = document.createElement("small"); small.textContent = data.created_at || nowIso();
  meta.appendChild(small);
  wrapContent.appendChild(p); wrapContent.appendChild(meta); wrap.appendChild(wrapContent);
  content.appendChild(wrap); conv.appendChild(content); item.appendChild(conv);
  list.appendChild(item);
  var sc = findScrollContainer(box, list);
  scrollToBottom(sc);
}

function createLocalEcho(text, youLabel){ const tempId="tmp_"+Math.random().toString(16).slice(2)+"_"+Date.now(); appendMessage({id:tempId,sender_name:youLabel||"",text:text,created_at:nowIso(),is_me:true}); return tempId; }

function getWsUrl(conversationId){
  const scheme = (window.location.protocol === "https:") ? "wss" : "ws";
  var host = window.location.hostname || '127.0.0.1';
  return scheme + '://' + host + ':8001/ws/chat/' + conversationId + '/';
}

function loadTranslation(key){ try{ var lang = localStorage.getItem('language') || 'en'; return fetch('/static/lang/'+lang+'.json', {credentials: 'same-origin'}).then(function(r){ if(!r.ok) return null; return r.json(); }).then(function(j){ return j && j[key] ? j[key] : null; }).catch(function(){ return null; }); }catch(e){ return Promise.resolve(null); } }

function init(){ const root=document.getElementById("chat-root") || document.getElementById("users-chat"); if(!root) return; if (root.dataset.wsInit === "1") return;
 root.dataset.wsInit = "1"; const conversationId=root.dataset.conversationId; const httpSendUrl=root.dataset.httpSendUrl; const userId=root.dataset.userId || ""; if(!conversationId) return; const form=document.getElementById("chatinput-form") || document.getElementById("chat-form"); const input=document.getElementById("chat-input"); if(!form||!input) return;

  // Autoscroll inicial: ejecutar solo una vez por carga para posicionar al último mensaje
  try{
    if(root.dataset.scrollInit !== "1"){
      root.dataset.scrollInit = "1";
      (function doInitialScroll(){
        try{
          var box = document.getElementById("chat-conversation") || document.getElementById("chat-messages");
          var list = document.getElementById("users-conversation") || document.getElementById("chat-messages-list") || (box?box.querySelector('#users-conversation'):null);
          var sc = findScrollContainer(box, list);
          scrollToBottom(sc);
          // ocultar spinner justo después del primer scroll
          try{ hideChatSpinner(); }catch(e){}
          setTimeout(function(){ scrollToBottom(findScrollContainer(box, list)); }, 0);
          setTimeout(function(){ scrollToBottom(findScrollContainer(box, list)); }, 250);
          setTimeout(function(){ scrollToBottom(findScrollContainer(box, list)); }, 1000);
        }catch(e){}
      })();
    }
  }catch(e){}

 let socket=null; let wsReady=false; let youLabel = null; let hadOpen = false;

function connect(){ try{ socket=new WebSocket(getWsUrl(conversationId)); }catch(e){ wsReady=false; return; }

if (DEBUG) console.log("[chat-ws] connecting:", getWsUrl(conversationId));


socket.onopen=function(){ wsReady=true; hadOpen = true; if (DEBUG) console.log("[chat-ws] open"); };
socket.onopen=function(){ wsReady=true; hadOpen = true; try{ hideChatSpinner(); }catch(e){} if (DEBUG) console.log("[chat-ws] open"); };

socket.onmessage=function(event){ if (DEBUG) console.log("[chat-ws] received raw:", event.data); const payload=safeJsonParse(event.data); if(!payload) return; let msg = null; if(payload.message) msg = payload.message; else msg = payload; if(!msg) return; const myUserId = String(root.dataset.userId||""); let isMe = false; if(msg.sender_id!=null){ isMe = myUserId && String(msg.sender_id)===myUserId; } else if(msg.sender_username!=null){ isMe = root.dataset.currentUsername && String(msg.sender_username)===String(root.dataset.currentUsername); } const id = msg.message_id || msg.id || msg.messageId; const sender_name = msg.sender_name || msg.sender_username || msg.sender || ""; const text = msg.content || msg.text || msg.contenido || ""; const created_at = msg.created_at || msg.fecha_creacion || nowIso(); appendMessage({id:id,sender_name:sender_name,text:text,created_at:created_at,is_me:isMe}); };


socket.onclose=function(event){ wsReady=false; if (DEBUG) console.log("[chat-ws] close", { code: event && event.code, reason: event && event.reason }); if(!hadOpen){ try{ showWsUnavailable(); }catch(e){} } };

socket.onerror=function(event){ wsReady=false; if (DEBUG) console.log("[chat-ws] error"); try{ showWsUnavailable(); }catch(e){} };
}

async function sendViaHttp(text){ if(!httpSendUrl) return; if (DEBUG) console.log("[chat-ws] sending http to:", httpSendUrl); const csrf=getCookie("csrftoken"); try{ const form = new URLSearchParams(); form.append('contenido', text); await fetch(httpSendUrl,{ method:'POST', headers:{ 'Content-Type':'application/x-www-form-urlencoded','X-CSRFToken':csrf||'' }, credentials: 'same-origin', body: form.toString() }); }catch(e){} }

function sendViaWs(text){ if(!socket||socket.readyState!==WebSocket.OPEN) return false; try{ const payload = {type:"message",content:text}; if (DEBUG) console.log("[chat-ws] sending ws payload:", payload); socket.send(JSON.stringify(payload)); return true; }catch(e){ return false; } }

form.addEventListener("submit",function(ev){ ev.preventDefault(); const text=(input.value||"").trim(); if(!text) return; input.value=""; const sent = (wsReady && sendViaWs(text)); if(!youLabel){ loadTranslation('chat.you').then(function(v){ youLabel = v || 'You'; createLocalEcho(text,youLabel); if(!sent) sendViaHttp(text); }); } else { createLocalEcho(text,youLabel); if(!sent) sendViaHttp(text); } });

connect();
}

function boot(){
  try { init(); } catch(e) {}
  // Reintento corto por si el template del chat se renderiza después
  setTimeout(function(){ try { init(); } catch(e) {} }, 250);
  setTimeout(function(){ try { init(); } catch(e) {} }, 1000);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}

})();
