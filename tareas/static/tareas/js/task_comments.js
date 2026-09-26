(function () {
    function csrfToken(root) {
        var input = root.querySelector("[data-comments-csrf] input[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function textFor(root, key, fallback) {
        var element = root.querySelector('[data-key="' + key + '"]');
        return element ? element.textContent : fallback;
    }

    function escapePath(template, id) {
        return template.replace("/0/", "/" + id + "/");
    }

    function unreadLabel(root, count) {
        return count >= 10 ? "9+" : String(count);
    }

    function appendText(root, key, fallback) {
        return textFor(root, key, fallback);
    }

    function commentDate(comment) {
        return new Date(comment.created_at);
    }

    function commentDateKey(comment) {
        return commentDate(comment).toLocaleDateString();
    }

    function initialsFor(comment) {
        var username = comment.autor && comment.autor.username ? comment.autor.username.trim() : "?";
        var parts = username.split(/\s+/).filter(Boolean);
        if (parts.length > 1) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
        return username.slice(0, 2).toUpperCase();
    }

    function renderDateSeparator(comment) {
        var separator = document.createElement("div");
        separator.className = "task-comments__date-separator";
        separator.dataset.commentDate = commentDateKey(comment);
        separator.textContent = commentDate(comment).toLocaleDateString();
        return separator;
    }

    function pendingFiles(form) {
        if (!form._pendingCommentFiles) form._pendingCommentFiles = [];
        return form._pendingCommentFiles;
    }

    function fileKey(file) {
        return [file.name, file.size, file.lastModified].join(":");
    }

    function formDataWithFiles(form) {
        var data = new FormData(form);
        data.delete("archivos");
        pendingFiles(form).forEach(function (file) { data.append("archivos", file, file.name); });
        return data;
    }

    function showFeedback(root, key, fallback) {
        var feedback = root.querySelector("[data-comments-feedback]");
        feedback.textContent = textFor(root, key, fallback);
        feedback.classList.remove("d-none");
    }

    function renderFilePreviews(root, form, previewSelector, summarySelector) {
        var preview = form.querySelector(previewSelector);
        var summary = summarySelector ? form.querySelector(summarySelector) : null;
        preview.replaceChildren();
        if (summary) summary.textContent = pendingFiles(form).length ? pendingFiles(form).length + " " + textFor(root, "tareas.comments.files_count", "archivos") : "";
        pendingFiles(form).forEach(function (file, index) {
            var item = document.createElement("span");
            item.className = "d-inline-flex align-items-center gap-1 me-2 mb-1 border rounded px-2 py-1";
            if (file.type.indexOf("image/") === 0) {
                var image = document.createElement("img");
                image.width = 36;
                image.height = 36;
                image.alt = file.name;
                image.className = "object-fit-cover";
                image.src = URL.createObjectURL(file);
                image.addEventListener("load", function () { URL.revokeObjectURL(image.src); }, { once: true });
                item.appendChild(image);
            } else {
                var icon = document.createElement("i");
                icon.className = "ri-file-line";
                icon.setAttribute("aria-hidden", "true");
                item.appendChild(icon);
            }
            var name = document.createElement("span");
            name.textContent = file.name;
            item.appendChild(name);
            var remove = document.createElement("button");
            remove.type = "button";
            remove.className = "btn btn-link btn-sm p-0";
            remove.title = textFor(root, "tareas.comments.remove_file", "Quitar archivo");
            remove.setAttribute("aria-label", remove.title);
            remove.textContent = "×";
            remove.addEventListener("click", function () {
                pendingFiles(form).splice(index, 1);
                renderFilePreviews(root, form, previewSelector, summarySelector);
            });
            item.appendChild(remove);
            preview.appendChild(item);
        });
    }

    function addFiles(root, form, files, previewSelector, summarySelector) {
        var before = pendingFiles(form).length;
        var existing = new Set(pendingFiles(form).map(fileKey));
        Array.from(files).forEach(function (file) {
            if (pendingFiles(form).length >= 5 || existing.has(fileKey(file))) return;
            pendingFiles(form).push(file);
            existing.add(fileKey(file));
        });
        if (before + files.length > 5) showFeedback(root, "tareas.comments.max_files", "Máximo cinco adjuntos.");
        renderFilePreviews(root, form, previewSelector, summarySelector);
    }

    function renderEditDocuments(root, form, comment) {
        var container = form.querySelector("[data-comments-edit-documents]");
        container.replaceChildren();
        (comment && comment.adjuntos ? comment.adjuntos : []).forEach(function (attachment) {
            var label = document.createElement("label");
            label.className = "d-block small";
            var checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.name = "documentos";
            checkbox.value = attachment.id;
            checkbox.checked = true;
            checkbox.className = "form-check-input me-1";
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(attachment.tipo || textFor(root, "tareas.comments.attachment", "Adjunto")));
            container.appendChild(label);
        });
    }

    function renderAttachment(root, attachment) {
        var link = document.createElement("a");
        link.className = "badge border text-body text-decoration-none me-1";
        link.href = attachment.archivo_url || attachment.url || "#";
        link.target = "_blank";
        link.rel = "noopener";
        var icon = document.createElement("i");
        var format = String(attachment.formato_archivo || "").toUpperCase();
        icon.className = format === "PDF" ? "ri-file-pdf-2-line me-1" : format.indexOf("JPG") >= 0 || format === "PNG" ? "ri-image-line me-1" : format.indexOf("XLS") >= 0 ? "ri-file-excel-2-line me-1" : "ri-file-line me-1";
        icon.setAttribute("aria-hidden", "true");
        link.appendChild(icon);
        var filename = attachment.nombre_archivo || attachment.tipo || textFor(root, "tareas.comments.attachment", "Adjunto");
        link.title = attachment.nombre_archivo || filename;
        link.appendChild(document.createTextNode(filename));
        if (attachment.nombre_archivo && attachment.tipo) {
            var type = document.createElement("small");
            type.className = "ms-1 text-muted";
            type.textContent = "· " + attachment.tipo;
            link.appendChild(type);
        }
        return link;
    }

    function renderHistory(root, comment, container) {
        var hasEditHistory = comment.historial && comment.historial.some(function (version) {
            return version.evento === "EDITADO";
        });
        if (!comment.puede_ver_historial || !hasEditHistory) return;
        var details = document.createElement("details");
        details.className = "task-comments__history small";
        var summary = document.createElement("summary");
        summary.textContent = textFor(root, "tareas.comments.history", "Historial");
        details.appendChild(summary);
        comment.historial.forEach(function (version) {
            var item = document.createElement("div");
            item.className = "border-start ps-2 mt-2";
            var header = document.createElement("div");
            header.className = "text-muted";
            header.textContent = (version.actor && version.actor.username ? version.actor.username : "") + " - " + new Date(version.fecha).toLocaleString();
            var body = document.createElement("div");
            body.textContent = version.contenido || "";
            item.appendChild(header);
            item.appendChild(body);
            details.appendChild(item);
        });
        container.appendChild(details);
    }

    function renderComment(root, comment) {
        if (!root._commentMap) root._commentMap = new Map();
        root._commentMap.set(String(comment.id), comment);
        var article = document.createElement("article");
        var isOwn = String(comment.autor && comment.autor.id) === root.dataset.currentUserId;
        article.className = "task-comments__message" + (isOwn ? " task-comments__message--own" : " task-comments__message--other");
        article.dataset.commentId = comment.id;
        article.dataset.commentDate = commentDateKey(comment);
        if (comment.tombstone) {
            article.classList.add("task-comments__message--tombstone");
            var tombstoneBubble = document.createElement("div");
            tombstoneBubble.className = "task-comments__bubble";
            var tombstone = document.createElement("span");
            tombstone.className = "text-muted fst-italic";
            tombstone.textContent = textFor(root, "tareas.comments.hidden", "Este comentario fue ocultado.");
            tombstoneBubble.appendChild(tombstone);
            article.appendChild(tombstoneBubble);
            return article;
        }
        var bubble = document.createElement("div");
        bubble.className = "task-comments__bubble";
        var avatar = document.createElement("span");
        avatar.className = "task-comments__avatar";
        var avatarUrl = comment.autor && comment.autor.avatar_url;
        if (avatarUrl && /^\/(?!\/)|^https?:\/\//.test(avatarUrl)) {
            var avatarImage = document.createElement("img");
            avatarImage.src = avatarUrl;
            avatarImage.alt = comment.autor ? comment.autor.username : "";
            avatarImage.addEventListener("error", function () {
                avatarImage.remove();
                avatar.textContent = initialsFor(comment);
            }, { once: true });
            avatar.appendChild(avatarImage);
        } else {
            avatar.textContent = initialsFor(comment);
        }
        avatar.title = comment.autor ? comment.autor.username : "";
        avatar.setAttribute("aria-label", comment.autor ? comment.autor.username : "");
        article.appendChild(avatar);
        article.appendChild(bubble);
        var header = document.createElement("div");
        header.className = "d-flex flex-wrap justify-content-between gap-2 task-comments__meta";
        var author = document.createElement("strong");
        author.className = "task-comments__author";
        author.textContent = comment.autor ? comment.autor.username : "";
        var date = document.createElement("span");
        date.className = "task-comments__date";
        date.textContent = commentDate(comment).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        date.title = commentDate(comment).toLocaleString();
        date.setAttribute("aria-label", commentDate(comment).toLocaleString());
        header.appendChild(author);
        header.appendChild(date);
        bubble.appendChild(header);
        var body = document.createElement("p");
        body.className = "task-comments__body comment-content";
        var content = comment.contenido || "";
        if (content.length > 500) {
            var preview = document.createElement("span");
            preview.textContent = content.slice(0, 500) + "...";
            var full = document.createElement("span");
            full.textContent = content;
            full.className = "d-none";
            var toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "btn btn-link btn-sm p-0 ms-1 align-baseline";
            toggle.textContent = appendText(root, "tareas.comments.more", "Ver más");
            toggle.addEventListener("click", function () {
                var expanded = !full.classList.contains("d-none");
                preview.classList.toggle("d-none", !expanded);
                full.classList.toggle("d-none", expanded);
                toggle.textContent = appendText(root, expanded ? "tareas.comments.more" : "tareas.comments.less", expanded ? "Ver más" : "Ver menos");
            });
            body.appendChild(preview);
            body.appendChild(full);
            body.appendChild(toggle);
        } else {
            body.textContent = content;
        }
        bubble.appendChild(body);
        if (comment.editado) {
            var edited = document.createElement("span");
            edited.className = "small text-muted me-2";
            edited.textContent = "(" + textFor(root, "tareas.comments.edited", "editado") + ")";
            body.appendChild(document.createTextNode(" "));
            body.appendChild(edited);
        }
        if (comment.oculto) {
            var hidden = document.createElement("span");
            hidden.className = "small text-muted me-2";
            hidden.textContent = "(" + textFor(root, "tareas.comments.hidden_state", "oculto") + ")";
            body.appendChild(document.createTextNode(" "));
            body.appendChild(hidden);
        }
        if (comment.adjuntos && comment.adjuntos.length) {
            var attachments = document.createElement("div");
            attachments.className = "task-comments__attachment-list";
            comment.adjuntos.forEach(function (attachment) {
                var link = renderAttachment(root, attachment);
                link.classList.add("task-comments__attachment");
                attachments.appendChild(link);
            });
            bubble.appendChild(attachments);
        }
        renderHistory(root, comment, bubble);
        var actions = document.createElement("div");
        actions.className = "task-comments__actions";
        var menu = document.createElement("div");
        menu.className = "dropdown-menu dropdown-menu-end";
        if (String(comment.autor && comment.autor.id) === root.dataset.currentUserId && root.dataset.canModify === "true") {
            var edit = document.createElement("button");
            edit.type = "button";
            edit.className = "dropdown-item";
            edit.dataset.commentAction = "edit";
            edit.dataset.commentId = comment.id;
            edit.dataset.commentContent = comment.contenido || "";
            edit.textContent = textFor(root, "tareas.comments.edit", "Editar");
            menu.appendChild(edit);
        }
        if (root.dataset.canSupervise === "true") {
            var visibility = document.createElement("button");
            visibility.type = "button";
            visibility.className = "dropdown-item";
            visibility.dataset.commentAction = comment.oculto ? "restore" : "hide";
            visibility.dataset.commentId = comment.id;
            visibility.textContent = textFor(root, comment.oculto ? "tareas.comments.restore" : "tareas.comments.hide", comment.oculto ? "Restaurar" : "Ocultar");
            menu.appendChild(visibility);
        }
        if (menu.childNodes.length) {
            var menuToggle = document.createElement("button");
            menuToggle.type = "button";
            menuToggle.className = "btn btn-sm task-comments__more";
            menuToggle.setAttribute("data-bs-toggle", "dropdown");
            menuToggle.setAttribute("aria-expanded", "false");
            menuToggle.setAttribute("aria-label", textFor(root, "tareas.comments.actions", "Acciones"));
            menuToggle.innerHTML = '<i class="ri-more-2-fill" aria-hidden="true"></i>';
            actions.appendChild(menuToggle);
            actions.appendChild(menu);
            bubble.appendChild(actions);
        }
        return article;
    }

    function syncComment(root, comment) {
        var feed = root.querySelector("[data-comments-feed]");
        var current = feed.querySelector('[data-comment-id="' + comment.id + '"]');
        var replacement = renderComment(root, comment);
        if (current) current.replaceWith(replacement);
    }

    function appendComment(root, comment) {
        var feed = root.querySelector("[data-comments-feed]");
        if (feed.querySelector('[data-comment-id="' + comment.id + '"]')) return false;
        var previousComments = feed.querySelectorAll("[data-comment-id]");
        var previous = previousComments.length ? previousComments[previousComments.length - 1] : null;
        if (previous && previous.dataset.commentDate !== commentDateKey(comment)) {
            feed.appendChild(renderDateSeparator(comment));
        }
        feed.appendChild(renderComment(root, comment));
        var loadedIds = new Set((root.dataset.loadedIds || "").split(",").filter(Boolean));
        loadedIds.add(String(comment.id));
        root.dataset.loadedIds = Array.from(loadedIds).join(",");
        root.querySelector("[data-comments-empty]").classList.add("d-none");
        return true;
    }

    function getLatestKnownCommentId(root) {
        var latestId = 0;
        if (root._commentMap) {
            root._commentMap.forEach(function (comment) {
                latestId = Math.max(latestId, Number(comment.id) || 0);
            });
        }
        return latestId;
    }

    function isNearBottom() {
        var feed = document.querySelector("[data-comments-feed]");
        return feed && feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
    }

    function appendPolledComments(root, comments) {
        var feed = root.querySelector("[data-comments-feed]");
        var wasNearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 160;
        comments.slice().sort(function (left, right) {
            var byDate = new Date(left.created_at) - new Date(right.created_at);
            return byDate || Number(left.id) - Number(right.id);
        }).forEach(function (comment) { appendComment(root, comment); });
        if (wasNearBottom && comments.length) {
            feed.scrollTop = feed.scrollHeight;
        }
    }

    function scheduleCommentsPoll(root) {
        if (root._commentsPollingStopped || document.hidden || !document.body.contains(root)) return;
        window.clearTimeout(root._commentsPollingTimer);
        root._commentsPollingTimer = window.setTimeout(function () {
            pollComments(root);
        }, 10000);
    }

    function pollComments(root) {
        if (root._commentsPollingInFlight || root._commentsPollingStopped || document.hidden) return;
        root._commentsPollingInFlight = true;
        var afterId = getLatestKnownCommentId(root);
        var url = root.dataset.feedUrl + "?after_id=" + encodeURIComponent(afterId);
        fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (response) {
                if (response.status === 401 || response.status === 403) {
                    root._commentsPollingStopped = true;
                }
                return response.json().then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function (result) {
                if (!result.ok || !result.data.success || root._commentsPollingStopped) return;
                appendPolledComments(root, result.data.comentarios || []);
            })
            .catch(function () {
                // A transient poll failure leaves the current feed untouched.
            })
            .finally(function () {
                root._commentsPollingInFlight = false;
                scheduleCommentsPoll(root);
            });
    }

    function startCommentsPolling(root) {
        root._commentsPollingInFlight = false;
        root._commentsPollingStopped = false;
        root._commentsVisibilityHandler = function () {
            if (document.hidden) {
                window.clearTimeout(root._commentsPollingTimer);
                return;
            }
            pollComments(root);
        };
        document.addEventListener("visibilitychange", root._commentsVisibilityHandler);
        scheduleCommentsPoll(root);
    }

    function postForm(url, form) {
        return fetch(url, {
            method: "POST",
            headers: { "X-CSRFToken": csrfToken(form), "X-Requested-With": "XMLHttpRequest" },
            body: formDataWithFiles(form),
        }).then(function (response) {
            return response.json().then(function (data) { return { ok: response.ok, data: data }; });
        });
    }

    function renderPage(root, data, prepend) {
        var feed = root.querySelector("[data-comments-feed]");
        var known = new Set((root.dataset.loadedIds || "").split(",").filter(Boolean));
        var comments = data.comentarios.filter(function (comment) {
            if (known.has(String(comment.id))) return false;
            known.add(String(comment.id));
            return true;
        });
        var fragment = document.createDocumentFragment();
        var previousDateKey = "";
        comments.forEach(function (comment) {
            if (!prepend && previousDateKey !== commentDateKey(comment)) {
                fragment.appendChild(renderDateSeparator(comment));
            }
            previousDateKey = commentDateKey(comment);
            var item = renderComment(root, comment);
            if (!prepend && data.primer_pendiente_id === comment.id) {
                var marker = root.querySelector("[data-comments-new-marker]").cloneNode(true);
                marker.classList.remove("d-none");
                marker.classList.add("d-flex");
                marker.querySelector("[data-comments-new-label]").textContent = textFor(root, "tareas.comments.new", "Nuevos comentarios");
                fragment.appendChild(marker);
            }
            fragment.appendChild(item);
        });
        if (prepend) {
            var beforeHeight = feed.scrollHeight;
            var beforeTop = feed.scrollTop;
            feed.prepend(fragment);
            root.dataset.beforeCommentId = data.before_comment_id || "";
            feed.scrollTop = beforeTop + feed.scrollHeight - beforeHeight;
        } else {
            feed.replaceChildren(fragment);
            root.dataset.beforeCommentId = data.before_comment_id || "";
            if (data.primer_pendiente_id) {
                var pending = feed.querySelector('[data-comment-id="' + data.primer_pendiente_id + '"]');
                if (pending) feed.scrollTop = Math.max(0, pending.offsetTop - feed.clientHeight / 3);
            } else {
                feed.scrollTop = feed.scrollHeight;
            }
        }
        root.dataset.loadedIds = Array.from(known).join(",");
        root.querySelector("[data-comments-empty]").classList.toggle("d-none", known.size > 0);
        root.querySelector("[data-comments-previous]").classList.toggle("d-none", !data.before_comment_id || data.comentarios.length < data.page_size);
        var unread = root.querySelector("[data-comments-unread]");
        unread.textContent = data.pendientes ? unreadLabel(root, data.pendientes) : "";
        unread.title = data.pendientes ? data.pendientes + " " + textFor(root, "tareas.comments.unread", "comentarios sin leer") : "";
        unread.classList.toggle("d-none", !data.pendientes);
        root.querySelector("[data-comments-read-controls]").classList.toggle("d-none", !known.size || !data.primer_pendiente_id);
    }

    function loadComments(root, url, prepend) {
        var status = root.querySelector("[data-comments-status]");
        status.textContent = textFor(root, "tareas.comments.loading", "Cargando...");
        return fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (response) { return response.json().then(function (data) { return { ok: response.ok, data: data }; }); })
            .then(function (result) {
                if (!result.ok || !result.data.success) throw new Error("comments");
                renderPage(root, result.data, Boolean(prepend));
                status.textContent = "";
                return result.data;
            })
            .catch(function () {
                status.textContent = textFor(root, "tareas.comments.load_error", "No fue posible cargar los comentarios.");
            });
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-comments-card]").forEach(function (root) {
            loadComments(root, root.dataset.feedUrl);
            startCommentsPolling(root);
            root.querySelector("[data-comments-previous]").addEventListener("click", function () {
                if (root.dataset.beforeCommentId) loadComments(root, root.dataset.feedUrl + "?before=" + root.dataset.beforeCommentId, true);
            });
            var composer = root.querySelector("[data-comments-composer]");
            composer?.querySelector("[data-comments-files]")?.addEventListener("change", function (event) {
                addFiles(root, composer, event.target.files, "[data-comments-preview]", "[data-comments-file-summary]");
                event.target.value = "";
            });
            composer?.addEventListener("submit", function (event) {
                event.preventDefault();
                var form = event.currentTarget;
                if (form.dataset.submitting === "true") return;
                form.dataset.submitting = "true";
                var submit = form.querySelector("[data-comments-submit]");
                submit.disabled = true;
                postForm(root.dataset.createUrl, form).then(function (result) {
                    if (!result.ok || !result.data.success) throw new Error("create");
                    form.reset();
                    pendingFiles(form).splice(0);
                    renderFilePreviews(root, form, "[data-comments-preview]", "[data-comments-file-summary]");
                    if (appendComment(root, result.data.comentario)) {
                        var feed = root.querySelector("[data-comments-feed]");
                        feed.scrollTop = feed.scrollHeight;
                    }
                }).catch(function () {
                    showFeedback(root, "tareas.comments.save_error", "No fue posible guardar el comentario.");
                }).finally(function () {
                    form.dataset.submitting = "false";
                    submit.disabled = false;
                });
            });
            root.querySelector("[data-comments-mark-read]").addEventListener("click", function (event) {
                var button = event.currentTarget;
                if (button.disabled) return;
                button.disabled = true;
                var form = document.createElement("form");
                var token = document.createElement("input");
                token.name = "csrfmiddlewaretoken";
                token.value = csrfToken(root);
                form.appendChild(token);
                root.dataset.loadedIds.split(",").filter(Boolean).forEach(function (id) {
                    var input = document.createElement("input"); input.name = "comentario_ids"; input.value = id; form.appendChild(input);
                });
                postForm(root.dataset.readUrl, form).then(function (result) {
                    if (!result.ok || !result.data.success) throw new Error("read");
                    loadComments(root, root.dataset.feedUrl);
                }).finally(function () {
                    button.disabled = false;
                });
            });
            root.addEventListener("click", function (event) {
                var button = event.target.closest("[data-comment-action]");
                if (!button) return;
                var action = button.dataset.commentAction;
                if (action === "edit") {
                    var editForm = document.querySelector("[data-comments-edit-form]");
                    var comment = root._commentMap.get(String(button.dataset.commentId));
                    editForm.querySelector("[data-comments-edit-content]").value = comment ? comment.contenido : button.dataset.commentContent;
                    editForm.dataset.commentId = button.dataset.commentId;
                    editForm._pendingCommentFiles = [];
                    renderEditDocuments(root, editForm, comment);
                    renderFilePreviews(root, editForm, "[data-comments-edit-preview]");
                    bootstrap.Modal.getOrCreateInstance(editForm.closest(".modal")).show();
                } else {
                    var reasonForm = document.querySelector("[data-comments-reason-form]");
                    reasonForm.dataset.commentId = button.dataset.commentId;
                    reasonForm.dataset.action = action;
                    reasonForm.querySelector("[data-comments-reason-title]").textContent = textFor(root, action === "hide" ? "tareas.comments.hide_title" : "tareas.comments.restore_title", action === "hide" ? "Ocultar comentario" : "Restaurar comentario");
                    reasonForm.querySelector("[data-comments-reason-submit]").textContent = textFor(root, action === "hide" ? "tareas.comments.hide" : "tareas.comments.restore", action === "hide" ? "Ocultar" : "Restaurar");
                    bootstrap.Modal.getOrCreateInstance(reasonForm.closest(".modal")).show();
                }
            });
            document.querySelector("[data-comments-edit-form]")?.addEventListener("submit", function (event) {
                event.preventDefault();
                var form = event.currentTarget;
                if (form.dataset.submitting === "true") return;
                form.dataset.submitting = "true";
                var submit = form.querySelector("button[type=submit]");
                submit.disabled = true;
                postForm(escapePath(root.dataset.editUrlTemplate, form.dataset.commentId), form).then(function (result) {
                    if (!result.ok || !result.data.success) throw new Error("edit");
                    syncComment(root, result.data.comentario);
                    bootstrap.Modal.getInstance(form.closest(".modal")).hide();
                    form.reset();
                    pendingFiles(form).splice(0);
                    renderFilePreviews(root, form, "[data-comments-edit-preview]");
                }).catch(function () {
                    showFeedback(root, "tareas.comments.save_error", "No fue posible guardar el comentario.");
                }).finally(function () {
                    form.dataset.submitting = "false";
                    submit.disabled = false;
                });
            });
            document.querySelector("[data-comments-reason-form]")?.addEventListener("submit", function (event) {
                event.preventDefault();
                var form = event.currentTarget;
                if (form.dataset.submitting === "true") return;
                form.dataset.submitting = "true";
                var submit = form.querySelector("[data-comments-reason-submit]");
                submit.disabled = true;
                var endpoint = form.dataset.action === "hide" ? root.dataset.hideUrlTemplate : root.dataset.restoreUrlTemplate;
                postForm(escapePath(endpoint, form.dataset.commentId), form).then(function (result) {
                    if (!result.ok || !result.data.success) throw new Error("visibility");
                    syncComment(root, result.data.comentario);
                    bootstrap.Modal.getInstance(form.closest(".modal")).hide(); form.reset();
                }).catch(function () {
                    showFeedback(root, "tareas.comments.save_error", "No fue posible guardar el comentario.");
                }).finally(function () {
                    form.dataset.submitting = "false";
                    submit.disabled = false;
                });
            });
            document.querySelector("[data-comments-edit-files]")?.addEventListener("change", function (event) {
                var form = document.querySelector("[data-comments-edit-form]");
                addFiles(root, form, event.target.files, "[data-comments-edit-preview]");
                event.target.value = "";
            });
        });
    });
}());