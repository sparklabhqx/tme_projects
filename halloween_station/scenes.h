#pragma once
#include "engine.h"

enum Scene { SC_MENU, SC_WHACK, SC_BAT, SC_CATCH };
extern Scene gScene;
extern int hiWhack, hiBat, hiCatch;

void scenesInit();   // compose all background layers (boot, once)

void menuEnter();  void menuTick();
void whackEnter(); void whackTick();
void batEnter();   void batTick();
void catchEnter(); void catchTick();

// ---- shared bits (common.cpp) ----
extern uint16_t *bgMenu, *bgWhack, *bgBat, *bgCatch;

void drawBackButton();
bool backTapped();                  // top-left skull button
void starsCompose(int count, uint32_t seed);      // onto current layer target
void hillsCompose(uint16_t color, int base, int amp1, int per1, int amp2, int per2, int phase);
void fillEllipse(int cx, int cy, int a, int b, uint16_t c);

// game-over overlay: call every frame once active; returns 0=showing, 1=again, 2=menu
int gameOverTick(const char* title, int score, int* best);
void gameOverReset();
