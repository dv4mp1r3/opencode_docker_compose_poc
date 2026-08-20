<?php
if (!defined('ABSPATH')) exit;
$settings = new Fake_Widget_Settings();
?>
<div class="wrap">
    <h1>Fake Widget Settings</h1>
    <form method="post" action="options.php">
        <?php settings_fields('fake_widget_group'); ?>
        <p>Limit: <?php echo esc_html($settings->get('limit', 5)); ?></p>
        <?php submit_button(); ?>
    </form>
</div>
