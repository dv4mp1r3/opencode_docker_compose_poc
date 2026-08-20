<?php
if (!defined('ABSPATH')) exit;

require_once FAKE_WIDGET_PLUGIN_DIR . 'includes/class-logger.php';
require_once FAKE_WIDGET_PLUGIN_DIR . 'includes/class-cache.php';
require_once FAKE_WIDGET_PLUGIN_DIR . 'includes/class-settings.php';
require_once FAKE_WIDGET_PLUGIN_DIR . 'includes/class-assets.php';
require_once FAKE_WIDGET_PLUGIN_DIR . 'includes/class-ajax-handler.php';
require_once FAKE_WIDGET_PLUGIN_DIR . 'includes/class-shortcode-manager.php';
require_once FAKE_WIDGET_PLUGIN_DIR . 'includes/class-widget-renderer.php';
require_once FAKE_WIDGET_PLUGIN_DIR . 'includes/class-i18n.php';

class Fake_Widget_Loader {
    public function init() {
        (new Fake_Widget_I18n())->register();
        (new Fake_Widget_Assets())->register();
        (new Fake_Widget_Ajax_Handler())->register();
        (new Fake_Widget_Shortcode_Manager())->register();

        if (is_admin()) {
            require_once FAKE_WIDGET_PLUGIN_DIR . 'admin/class-admin-page.php';
            require_once FAKE_WIDGET_PLUGIN_DIR . 'admin/class-admin-settings.php';
            (new Fake_Widget_Admin_Page())->register();
        } else {
            require_once FAKE_WIDGET_PLUGIN_DIR . 'public/class-public.php';
            (new Fake_Widget_Public())->register();
        }
    }
}
