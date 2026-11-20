// The JSON the API sends. Every number here was computed by code (submit_plan), never typed by the model.

export type Nutrients = { calories: number; protein_g: number; carbs_g: number; fiber_g: number; sugar_g: number };

export type RecipeNutrition = {
  per_serving?: Nutrients;
  servings: number | "unknown";
  per?: string; // "serving", "muffin", "cup"...
  whole_recipe: Nutrients;
  lines_not_counted: number;
};

export type PlanRecipe = {
  title: string;
  page: number;
  category: string;
  photo_id: string | null;
  batches: number;
  allergens: string[];
  nutrition: RecipeNutrition | null;
};

export type Line = {
  id: string;
  name: string;
  size: string;
  price: number;
  quantity: number;
  line_total: number;
  protein_g: number | null;
};

export type Meal = "breakfast" | "lunch" | "dinner";

export type Plan = {
  note: string;
  recipes: PlanRecipe[];
  lines: Line[];
  total: number;
  budget: number;
  left: number;
  no_label: string[];
  protein_g_per_day: number; // from groceries bought (leftovers included)
  eaten_per_day: Nutrients; // from recipes x batches: what the student eats
  meals: Meal[];
  meals_target: number;
  meals_planned: number;
  budget_limited: boolean;
  calendar: Record<string, Partial<Record<Meal, string | null>>>;
  protein_goal_g_per_day?: number;
  goal_met?: boolean;
  protein_short_g_per_day?: number;
  seconds: number;
  cost: number;
};

export type Step = { tool: string; text: string; seconds: number };

export type Product = {
  product_id: string;
  name: string;
  size: string;
  regular: number;
  promo: number | null;
  best: number;
  unit: string;
  unit_price: number | null;
  nutrition: { protein_g: number } | null;
};

export type FullRecipe = {
  title: string;
  book_page: number;
  makes: string | null;
  ingredient_groups: { name: string | null; items: string[] }[];
  steps: string;
  photo_id: string | null;
  nutrition: RecipeNutrition | null;
};
