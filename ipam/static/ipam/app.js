// Zanjirli selectlar: viloyat → tuman → filial → qurilma.
// Bola select'ning har bir varianti data-parent="<ota ID>" ga ega,
// ota select o'zgarganda faqat mos variantlar ko'rsatiladi.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("select[data-chain-parent]").forEach(function (child) {
    var parent = document.getElementById(child.dataset.chainParent);
    if (!parent) return;
    var options = Array.prototype.slice.call(child.options);

    // Ota tanlangan bo'lsa — faqat unga tegishlilar ko'rinadi.
    // Ota bo'sh bo'lsa — otaning hozir ko'rinib turgan variantlariga tegishlilar
    // (masalan, viloyat tanlanib tuman tanlanmasa, shu viloyatning barcha filiallari).
    function isVisible(opt) {
      var value = parent.value;
      if (value) return opt.dataset.parent === value;
      if (!opt.dataset.parent) return true;
      var parentOpt = parent.querySelector('option[value="' + opt.dataset.parent + '"]');
      return !parentOpt || !parentOpt.disabled;
    }

    function apply(onLoad) {
      options.forEach(function (opt) {
        if (!opt.value) return;
        var visible = isVisible(opt);
        opt.hidden = !visible;
        opt.disabled = !visible;
      });
      var selected = child.options[child.selectedIndex];
      if (selected && selected.disabled) child.value = "";
      // Keyingi zanjir (masalan, filial → qurilma) ham yangilansin
      if (!onLoad) child.dispatchEvent(new Event("change", { bubbles: true }));
    }

    parent.addEventListener("change", function () { apply(false); });
    apply(true);
  });

  // Filtr formalarida tanlov o'zgarishi bilan darhol qidirish
  document.querySelectorAll("form.filters").forEach(function (form) {
    var pending = false;
    form.addEventListener("change", function (event) {
      if (event.target.tagName !== "SELECT" || pending) return;
      // Zanjir bo'ylab bir nechta change kelishi mumkin — bir marta yuboramiz
      pending = true;
      setTimeout(function () { form.requestSubmit(); }, 0);
    });
  });
});
