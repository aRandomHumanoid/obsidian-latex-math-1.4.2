import LatexMathPlugin from 'LatexMathPlugin';
import { App, PluginSettingTab, Setting} from 'obsidian';

// Settings tab for Latex Math plugin.
export class LmatSettingsTab extends PluginSettingTab {
    plugin: LatexMathPlugin;

    constructor(app: App, plugin: LatexMathPlugin) {
        super(app, plugin);
        this.plugin = plugin;
    }

    display(): void {
        this.containerEl.empty();

        new Setting(this.containerEl)
            .setName('Smart Solve result marker')
            .setDesc('LaTeX inserted between the source and the result when Smart Solve writes a display result. Example values: \\Rightarrow, \\to, \\implies. Empty restores the default \\Rightarrow. Existing markers in your notes are still detected on refresh regardless of this setting.')
            .addText((text) => {
                text.setPlaceholder('\\Rightarrow')
                    .setValue(this.plugin.settings.smart_solve_result_marker)
                    .onChange(async (value) => {
                        this.plugin.settings.smart_solve_result_marker = value;
                        await this.plugin.saveSettings();
                    });
            });

        new Setting(this.containerEl)
            .setName('Developer mode')
            .setDesc('Use python source files and venv instead of bundled executable.\nReload Obsidian to apply.')
            .addToggle((toggle) => {
                toggle.setValue(this.plugin.settings.dev_mode)
                    .onChange(async (value) => {
                        this.plugin.settings.dev_mode = value;
                        await this.plugin.saveSettings();
                    });
            });
    }

}
