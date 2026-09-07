# Table & Tale v3.0

**Recipes worth remembering.**

Table & Tale is a locally hosted, invite-only digital family cookbook. The Windows PC is the source of truth, while HTTPS remote access can make the same private cookbook available to close friends and family from normal phone and desktop browsers.

## v3 architecture

- Flask + Waitress application server
- SQLite source-of-truth database
- local uploads for dish photos, profile photos, and original recipe cards
- Tesseract OCR support for recipe-card transcription
- PWA frontend for mobile and desktop
- additive database migrations from the existing Family Cookbook database
- automatic nightly backups
- optional Tailscale Funnel / Cloudflare Tunnel remote access

## Upgrade safety

The v3 installer does not replace or reseed an existing `cookbook.db`.

Existing user IDs, usernames, password hashes, roles, ratings, comments, favorites, recipes, and cook history remain in the original database. New v3 columns and tables are added through SQLite migrations.

The installer creates a pre-upgrade restore point and validates the existing user count after the server starts. Failed upgrades roll back automatically.

## Core family features

- Admin, Member, and Guest accounts
- invite-only registration
- profile photos
- recipe contributor attribution
- ratings and comments
- favorites and Made It history
- family activity feed
- private personal notes
- recipe edit history
- original recipe provenance and family stories

## Recipe structure

Ingredients are stored as structured rows with quantity, unit, ingredient, preparation note, grocery aisle, optional status, and whether the quantity scales.

Cooking steps are structured separately. Each step can link the ingredients used in that step and what fraction of the recipe quantity is used. This allows scaled quantities to appear inside Cook Mode rather than only in the master ingredient list.

Legacy recipes remain intact and are automatically converted into basic steps where possible. They are marked **Needs Review** until a family member confirms the structured quantities, temperatures, times, and step ingredient allocations.

## Dynamic scaling

Recipes can be scaled by target servings or from one ingredient on hand. The scale is temporary to the current cooking session and never edits the shared family recipe.

Example: if a recipe calls for 1 lb ground beef and you enter 0.5 lb on hand, the current view scales to 0.5× and adjusts every scalable ingredient and linked step quantity.

Temperatures are never mathematically scaled. Cook time is not blindly multiplied either. Structured steps keep their actual temperature, time, and doneness guidance.

## Cook Mode

Cook Mode is full screen and presents one step at a time with:

- Previous / Next navigation
- progress
- exact ingredients used in that step at the current scale
- oven/pan temperature
- time
- doneness cue
- tap-to-start timer
- optional Screen Wake Lock

Screen Wake Lock asks supported browsers to keep the display awake. Browsers cannot directly set hardware screen brightness.

## Import Center

Supported sources:

- Recipe websites using Recipe JSON-LD
- ChatGPT shared links beginning with `https://chatgpt.com/share/`
- pasted recipe text
- one or more recipe-card/cookbook photos

Every import is a draft for human review before saving. Original card images are retained as recipe sources.

ChatGPT share-page parsing is best-effort because shared conversation pages are not a formal recipe API. If a shared page cannot be parsed cleanly, use Paste Text as the fallback.

## Categories

Primary categories are separate dimensions from equipment/tags:

- Main Dishes
- Breakfast & Brunch
- Sides
- Appetizers & Snacks
- Desserts
- Drinks
- Breads & Baking
- Sauces & Condiments

Existing `Dinner & Savory`, `Breakfast & Sides`, `Coffee & Drinks`, and `Frozen & Dessert` records are migrated without deleting recipes.

## Pairings

Main dishes can show recommended Side, Drink, and Dessert pairings from the family cookbook. Family-owned pairings can be pinned. The main recipe plus the displayed pairings can be added to a shopping list as one meal.

## Branding and dark mode

The v3 working brand is **Table & Tale** with the tagline **Recipes worth remembering.**

Admins can change the cookbook name, tagline, and accent color from the application. Each user can choose Light, Dark, or Follow Device appearance.
