// ---------- Email 樣板搜尋（前端即時過濾，不打後端） ----------
document.getElementById('planSearch').addEventListener('input', function (e) {
    var keyword = e.target.value.trim().toLowerCase();
    var rows = document.querySelectorAll('#templates-table tr[id^="row-"]');

    rows.forEach(function (row) {
        var planCode = row.querySelector('td:first-child').textContent.toLowerCase();
        var name = row.querySelector('.cell-name').textContent.toLowerCase();
        var match = planCode.indexOf(keyword) !== -1 || name.indexOf(keyword) !== -1;
        row.style.display = match ? '' : 'none';
    });
});

// ---------- 圖示渲染（lucide） ----------
// 每次畫面上新增/更新了帶有 data-lucide 屬性的節點後都要重新呼叫一次，
// 否則新插入的 <i data-lucide="..."> 不會被換成實際的 SVG 圖示
function renderIcons() {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
    }
}

// ---------- Tab 切換 ----------
function switchTab(tabId) {
    document.querySelectorAll('.tab-panel').forEach(function (el) {
        el.classList.remove('active');
    });
    document.querySelectorAll('.tab-btn').forEach(function (el) {
        el.classList.remove('active');
    });
    document.getElementById('panel-' + tabId).classList.add('active');
    document.getElementById('tabbtn-' + tabId).classList.add('active');

    // 記住上次選的分頁，重新整理後停留在同一頁
    try { localStorage.setItem('activeTab', tabId); } catch (e) {}

    // Quill 編輯器要在容器可見之後才初始化尺寸正確，切到樣板分頁時補一次 resize
    if (tabId === 'templates' && window.quillModal) {
        window.quillModal.update();
    }
}

// ---------- 進階篩選 展開/收合 ----------
function toggleAdvanced() {
    var panel = document.getElementById('advancedFilters');
    var toggleBtn = document.getElementById('advancedToggle');
    var isOpen = panel.classList.toggle('open');
    toggleBtn.classList.toggle('open', isOpen);

    // 如果目前收合區塊裡有值（例如帶著查詢字串重新整理頁面），預設展開讓使用者看得到
    try { localStorage.setItem('advancedFiltersOpen', isOpen ? '1' : '0'); } catch (e) {}
}

document.addEventListener('DOMContentLoaded', function () {
    var saved = null;
    try { saved = localStorage.getItem('activeTab'); } catch (e) {}
    var validTabs = ['orders', 'templates', 'vendors'];
    switchTab(validTabs.includes(saved) ? saved : 'orders');

    // 若進階篩選欄位本來就有值（帶著查詢條件重新整理），自動展開
    var advancedFilters = document.getElementById('advancedFilters');
    var hasAdvancedValue = Array.prototype.some.call(
        advancedFilters.querySelectorAll('input'),
        function (input) { return input.value; }
    );
    var savedOpen = null;
    try { savedOpen = localStorage.getItem('advancedFiltersOpen'); } catch (e) {}
    if (hasAdvancedValue || savedOpen === '1') {
        advancedFilters.classList.add('open');
        document.getElementById('advancedToggle').classList.add('open');
    }

    renderIcons();
});

// ---------- Email 樣板 Modal ----------
var quillModal = null;

function initQuill() {
    if (!quillModal) {
        quillModal = new Quill('#modalEditor', { theme: 'snow' });
        window.quillModal = quillModal;
    }
}

var modalMode = 'edit'; // 'edit' | 'new'，用來記住目前 modal 是編輯還是新增模式

function openModal(pc) {
    initQuill();
    modalMode = 'edit';
    var data = (window.TEMPLATES && window.TEMPLATES[pc]) || { product_name: '', subject: '', intro_note: '' };
    document.getElementById('modalTitle').innerText = '編輯樣板：' + pc;
    document.getElementById('modalPlanCode').value = pc;
    document.getElementById('modalPlanCodeInput').value = pc;
    document.getElementById('modalPlanCodeInput').disabled = true;
    document.getElementById('modalProductName').value = data.product_name;
    document.getElementById('modalSubjectEditable').innerHTML = placeholdersToLockedHtml(data.subject);
    setEditorWithLockedPlaceholders(data.intro_note);
    document.getElementById('modalError').innerText = '';
    document.getElementById('modalPlanCodeError').innerText = '';
    document.getElementById('modalOverlay').classList.add('show');
}

function openNewModal() {
    initQuill();
    modalMode = 'new';
    document.getElementById('modalTitle').innerText = '新增產品樣板';
    document.getElementById('modalPlanCode').value = '';
    document.getElementById('modalPlanCodeInput').value = '';
    document.getElementById('modalPlanCodeInput').disabled = false;
    document.getElementById('modalProductName').value = '';
    document.getElementById('modalSubjectEditable').innerHTML = placeholdersToLockedHtml('[[product_name]]（共[[count]]張）');
    setEditorWithLockedPlaceholders('你好，以下是你的 [[product_name]] 安裝說明：');
    document.getElementById('modalError').innerText = '';
    document.getElementById('modalPlanCodeError').innerText = '';
    document.getElementById('modalOverlay').classList.add('show');
    
    // modal 開啟動畫跑完後把游標放進 PlanCode 欄位，體感比較順
    setTimeout(function () {
        document.getElementById('modalPlanCodeInput').focus();
    }, 180);
}

// ---------- 複製樣板：以現有樣板內容為基礎，開啟「新增」視窗讓使用者輸入新的 PlanCode ----------
function copyTemplate(pc) {
    initQuill();
    var source = (window.TEMPLATES && window.TEMPLATES[pc]) || { product_name: '', subject: '', intro_note: '' };

    modalMode = 'new';
    document.getElementById('modalTitle').innerText = '複製樣板（來源：' + pc + '）';
    document.getElementById('modalPlanCode').value = '';
    document.getElementById('modalPlanCodeInput').value = '';
    document.getElementById('modalPlanCodeInput').disabled = false;
    document.getElementById('modalProductName').value = source.product_name ? (source.product_name + ' (複製)') : '';
    document.getElementById('modalSubjectEditable').innerHTML = placeholdersToLockedHtml(source.subject || '');
    setEditorWithLockedPlaceholders(source.intro_note || '');
    document.getElementById('modalError').innerText = '';
    document.getElementById('modalPlanCodeError').innerText = '';
    document.getElementById('modalOverlay').classList.add('show');

    setTimeout(function () {
        document.getElementById('modalPlanCodeInput').focus();
    }, 180);
}

function closeModal() {
    document.getElementById('modalOverlay').classList.remove('show');
}

function saveModal() {
    var pc = document.getElementById('modalPlanCodeInput').value.trim();
    document.getElementById('modalPlanCodeError').innerText = '';

    if (modalMode === 'new') {
        if (!pc) {
            document.getElementById('modalPlanCodeError').innerText = '請輸入 PlanCode';
            return;
        }
        if (!/^[A-Za-z0-9_\-]+$/.test(pc)) {
            document.getElementById('modalPlanCodeError').innerText = 'PlanCode 只能包含英數字、底線、連字號';
            return;
        }
        if (window.TEMPLATES && window.TEMPLATES[pc]) {
            document.getElementById('modalPlanCodeError').innerText = '這個 PlanCode 已經有樣板了，請改用「編輯」';
            return;
        }
    }

    document.getElementById('modalPlanCode').value = pc;
    var payload = {
        PlanCode: pc,
        product_name: document.getElementById('modalProductName').value,
        subject: lockedHtmlToPlaceholders(document.getElementById('modalSubjectEditable')),
        intro_note: getEditorHtmlWithPlaceholders()
    };
    fetch('/admin/templates/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
        .then(function (res) { return res.json(); })
        .then(function (result) {
            if (!result.success) {
                document.getElementById('modalError').innerText = result.message || '儲存失敗';
                return;
            }
            window.TEMPLATES[pc] = {
                product_name: result.product_name,
                subject: result.subject,
                intro_note: result.intro_note
            };
            var row = document.getElementById('row-' + pc);
            if (row) {
                row.querySelector('.cell-name').innerText = result.product_name || '-';
                row.querySelector('.cell-updated').innerText = result.updated_at;
            } else {
                var table = document.querySelector('#templates-table');
                var tr = document.createElement('tr');
                tr.id = 'row-' + pc;
                tr.innerHTML =
                    '<td>' + pc + '</td>' +
                    '<td class="cell-name">' + (result.product_name || '-') + '</td>' +
                    '<td class="cell-updated">' + result.updated_at + '</td>' +
                    '<td>' +
                    '<span class="table-actions">' +
                    '<button type="button" class="icon-btn" title="編輯" onclick="openModal(\'' + pc + '\')"><i data-lucide="pencil"></i></button>' +
                    '<a href="/admin/templates/preview/' + pc + '" target="_blank" class="icon-btn" title="預覽"><i data-lucide="eye"></i></a>' +
                    '<button type="button" class="icon-btn" title="複製" onclick="copyTemplate(\'' + pc + '\')"><i data-lucide="copy"></i></button>' +
                    '</span>' +
                    '</td>';
                table.appendChild(tr);
                renderIcons(); // 新插入的列裡有全新的 data-lucide 節點，需要重新渲染
            }
            closeModal();
        })
        .catch(function (err) {
            document.getElementById('modalError').innerText = '網路錯誤：' + err;
        });
}
function toggleNote(el) {
    el.classList.toggle('expanded');
}
// ---------- 鎖定灰字：把 [[key]] 轉成不可編輯的灰色 span，反向轉回時用 ----------
var LOCKED_LABELS = { product_name: '示範方案', count: '2' };

function placeholdersToLockedHtml(text) {
    return (text || '').replace(/\[\[(\w+)\]\]/g, function (m, key) {
        var label = LOCKED_LABELS[key] || key;
        return '<span class="locked-chip" contenteditable="false" data-key="' + key + '">' + label + '</span>';
    });
}

function lockedHtmlToPlaceholders(container) {
    var clone = container.cloneNode(true);
    clone.querySelectorAll('.locked-chip').forEach(function (el) {
        el.replaceWith('[[' + el.getAttribute('data-key') + ']]');
    });
    return clone.textContent;
}

// Quill embed blot：讓內容編輯器裡的灰字也不可編輯
var Embed = Quill.import('blots/embed');
class PlaceholderBlot extends Embed {
    static create(key) {
        var node = super.create();
        node.setAttribute('data-key', key);
        node.classList.add('locked-chip');
        node.innerText = LOCKED_LABELS[key] || key;
        return node;
    }
    static value(node) {
        return node.getAttribute('data-key');
    }
}
PlaceholderBlot.blotName = 'placeholder';
PlaceholderBlot.tagName = 'span';
Quill.register(PlaceholderBlot);

// 用不可見的特殊字元包住 [[key]]，避免被 HTML parser 誤判成一般文字
var PLACEHOLDER_MARK_OPEN = '\uE000';
var PLACEHOLDER_MARK_CLOSE = '\uE001';

function setEditorWithLockedPlaceholders(html) {
    // 先把 [[key]] 換成不會被 HTML parser 破壞的特殊標記字元
    var marked = (html || '').replace(/\[\[(\w+)\]\]/g, function (m, key) {
        return PLACEHOLDER_MARK_OPEN + key + PLACEHOLDER_MARK_CLOSE;
    });

    // 用 Quill 的 clipboard 功能「真的」把 HTML 解析進編輯器，
    // 會正確產生 <p> <strong> <br> 等對應的排版格式，不再當純文字塞進去
    quillModal.setText('');
    quillModal.clipboard.dangerouslyPasteHTML(0, marked);

    // 貼上後，把裡面的標記字元轉成不可編輯的 placeholder 灰字方塊
    var delta = quillModal.getContents();
    var newOps = [];
    var markerRegex = new RegExp(PLACEHOLDER_MARK_OPEN + '(\\w+)' + PLACEHOLDER_MARK_CLOSE, 'g');

    delta.ops.forEach(function (op) {
        if (typeof op.insert !== 'string' || op.insert.indexOf(PLACEHOLDER_MARK_OPEN) === -1) {
            newOps.push(op);
            return;
        }
        var text = op.insert;
        var lastIndex = 0;
        var match;
        markerRegex.lastIndex = 0;
        while ((match = markerRegex.exec(text)) !== null) {
            if (match.index > lastIndex) {
                newOps.push({ insert: text.slice(lastIndex, match.index), attributes: op.attributes });
            }
            newOps.push({ insert: { placeholder: match[1] } });
            lastIndex = markerRegex.lastIndex;
        }
        if (lastIndex < text.length) {
            newOps.push({ insert: text.slice(lastIndex), attributes: op.attributes });
        }
    });

    quillModal.setContents({ ops: newOps });
}

function getEditorHtmlWithPlaceholders() {
    // 直接拿 Quill 渲染出來的「真正 HTML」（含 <p> <strong> <br> 等標籤），
    // 而不是只處理純文字加換行，這樣粗體/清單等格式才不會遺失
    var html = quillModal.root.innerHTML;

    // 把裡面的灰字方塊（placeholder embed）換回 [[key]] 純文字標記
    var temp = document.createElement('div');
    temp.innerHTML = html;
    temp.querySelectorAll('.locked-chip').forEach(function (el) {
        el.replaceWith('[[' + el.getAttribute('data-key') + ']]');
    });
    return temp.innerHTML;
}