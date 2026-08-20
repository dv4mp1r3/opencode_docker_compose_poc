<?php
if (!defined('ABSPATH')) exit;

class Fake_Widget_Renderer {
    public function render(array $atts) {
        $template = $atts['mode'] === 'compact'
            ? 'templates/widget-compact.php'
            : 'templates/widget-default.php';

        $cache = new Fake_Widget_Cache();
        $cache_key = 'fake_widget_' . md5(serialize($atts));

        $cached = $cache->get($cache_key);
        if ($cached !== false) {
            return $cached;
        }

        ob_start();
        $limit = (int) $atts['limit'];
        include FAKE_WIDGET_PLUGIN_DIR . $template;
        $html = ob_get_clean();

        $cache->set($cache_key, $html, 300);
        return $html;
    }
}
