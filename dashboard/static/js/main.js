import { initHeader } from './header.js';
import { initControlBoard } from './control_board.js';
import { historyBoard } from './history_board.js';
import { strategyDrawer } from './strategy_drawer.js';
import { researchLibrary } from './research_library.js';

window.addEventListener("load", () => {
    initHeader();
    initControlBoard();
    historyBoard.init();
    strategyDrawer.init();
    researchLibrary.init();
});
