(function () {
    document.addEventListener('DOMContentLoaded', function () {
        var widgets = document.querySelectorAll('.fake-widget');
        widgets.forEach(function (w) {
            w.dataset.ready = 'true';
        });
    });
})();
