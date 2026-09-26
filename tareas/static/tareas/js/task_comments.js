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
                var icon = document.createElement("span");
                icon.setAttribute("aria-hidden", "true");
                icon.textContent = "[file]";
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
        link.className = "badge text-bg-light text-decoration-none me-1";
        link.href = attachment.archivo_url || attachment.url || "#";
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = attachment.tipo || textFor(root, "tareas.comments.attachment", "Adjunto");
        return link;
    }

    function renderHistory(root, comment, container) {
        if (!comment.puede_ver_historial || !comment.historial || !comment.historial.length) return;
        var details = document.createElement("details");
        details.className = "mt-2 small";
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
        article.className = "border rounded p-3";
        article.dataset.commentId = comment.id;
        if (comment.tombstone) {
            article.classList.add("bg-light");
            var tombstone = document.createElement("span");
            tombstone.className = "text-muted fst-italic";
            tombstone.textContent = textFor(root, "tareas.comments.hidden", "Este comentario fue ocultado.");
            article.appendChild(tombstone);
            return article;
        }
        var header = document.createElement("div");
        header.className = "d-flex flex-wrap justify-content-between gap-2 small text-muted";
        var author = document.createElement("strong");
        author.className = "text-body";
        author.textContent = comment.autor ? comment.autor.username : "";
        var date = document.createElement("span");
        date.textContent = new Date(comment.created_at).toLocaleString();
        header.appendChild(author);
        header.appendChild(date);
        article.appendChild(header);
        var body = document.createElement("p");
        body.className = "mb-2 mt-2 comment-content";
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
        article.appendChild(body);
        if (comment.editado) {
            var edited = document.createElement("span");
            edited.className = "small text-muted me-2";
            edited.textContent = "(" + textFor(root, "tareas.comments.edited", "editado") + ")";
            body.appendChild(document.createTextNode(" "));
            body.appendChild(edited);
        }
        if (comment.adjuntos && comment.adjuntos.length) {
            var attachments = document.createElement("div");
            comment.adjuntos.forEach(function (attachment) { attachments.appendChild(renderAttachment(root, attachment)); });
            article.appendChild(attachments);
        }
        renderHistory(root, comment, article);
        var actions = document.createElement("div");
        actions.className = "d-flex gap-2 mt-2";
        if (String(comment.autor && comment.autor.id) === root.dataset.currentUserId && root.dataset.canModify === "true") {
            var edit = document.createElement("button");
            edit.type = "button";
            edit.className = "btn btn-sm btn-outline-secondary";
            edit.dataset.commentAction = "edit";
            edit.dataset.commentId = comment.id;
            edit.dataset.commentContent = comment.contenido || "";
            edit.textContent = textFor(root, "tareas.comments.edit", "Editar");
            actions.appendChild(edit);
        }
        if (root.dataset.canSupervise === "true") {
            var visibility = document.createElement("button");
            visibility.type = "button";
            visibility.className = "btn btn-sm btn-outline-secondary";
            visibility.dataset.commentAction = comment.oculto ? "restore" : "hide";
            visibility.dataset.commentId = comment.id;
            visibility.textContent = textFor(root, comment.oculto ? "tareas.comments.restore" : "tareas.comments.hide", comment.oculto ? "Restaurar" : "Ocultar");
            actions.appendChild(visibility);
        }
        if (actions.childNodes.length) article.appendChild(actions);
        return article;
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
        comments.forEach(function (comment) {
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
            feed.prepend(fragment);
            root.dataset.beforeCommentId = data.before_comment_id || "";
            window.scrollBy(0, feed.scrollHeight - beforeHeight);
        } else {
            feed.replaceChildren(fragment);
            root.dataset.beforeCommentId = data.before_comment_id || "";
            if (data.primer_pendiente_id) {
                var pending = feed.querySelector('[data-comment-id="' + data.primer_pendiente_id + '"]');
                if (pending) pending.scrollIntoView({ block: "center", behavior: "smooth" });
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
                    return loadComments(root, root.dataset.feedUrl);
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
                    bootstrap.Modal.getInstance(form.closest(".modal")).hide(); loadComments(root, root.dataset.feedUrl);
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
                    bootstrap.Modal.getInstance(form.closest(".modal")).hide(); form.reset(); loadComments(root, root.dataset.feedUrl);
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