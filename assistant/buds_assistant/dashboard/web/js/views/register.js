// Views register themselves here (one import per view file).
import { html } from "../../vendor/htm-preact-standalone.module.js";
import { registerView } from "../main.js";
import { People, Person } from "./people.js";
import { Library, Conversation } from "./library.js";
import { Settings } from "./settings.js";
import { Setup } from "./onboarding.js";
import { Developer } from "./developer.js";
import { MyDay } from "./me.js";
import { Controls } from "./controls.js";

registerView("people", ({ id }) => (id ? html`<${Person} id=${id} key=${id} />` : html`<${People} />`));
registerView("library", ({ id }) => (id ? html`<${Conversation} id=${id} key=${id} />` : html`<${Library} />`));
registerView("settings", () => html`<${Settings} />`);
registerView("setup", () => html`<${Setup} />`);
registerView("dev", () => html`<${Developer} />`);
registerView("me", () => html`<${MyDay} />`);
registerView("controls", () => html`<${Controls} />`);
