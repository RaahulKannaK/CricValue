from django.db import models
from .categories import CATEGORY_CHOICES
from .categories import CATEGORY_CHOICES, group_title

class Player(models.Model):
    name = models.CharField(max_length=100)
    country = models.CharField(max_length=60)
    role = models.CharField(max_length=30, choices=[
        ("BAT", "Batter"), ("BOWL", "Bowler"), ("AR", "All-rounder"), ("WK", "Wicketkeeper")])
    cricsheet_id = models.CharField(max_length=20, blank=True, null=True, unique=True)
    date_of_birth = models.DateField(null=True, blank=True, help_text="Optional verified date of birth; never inferred from match count.")
    potential_rating = models.FloatField(null=True, blank=True, help_text="Optional scouting input from 0-100. Leave blank to use a neutral evidence-based estimate.")
    base_value = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    base_locked = models.BooleanField(default=False)
    form_score = models.FloatField(default=50)
    form_premium = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    last_played = models.DateField(null=True, blank=True, db_index=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    @property
    def total_value(self):
        return self.base_value + self.form_premium

    def __str__(self):
        return f"{self.name} ({self.country})"


class Match(models.Model):
    FORMATS = [("T20", "T20"), ("ODI", "ODI"), ("TEST", "Test")]
    date = models.DateField()
    competition = models.CharField(max_length=80)
    level = models.CharField(max_length=15, choices=[
        ("INTL", "International"), ("LEAGUE", "League"), ("DOM", "Domestic")], default="INTL")
    fmt = models.CharField(max_length=4, choices=FORMATS, default="T20")
    category = models.CharField(max_length=10, blank=True, default="", db_index=True)
    teams = models.CharField(max_length=160, blank=True, default="")
    # {"India": [player_id, ...], "Zimbabwe": [player_id, ...]}
    # Captured from the source match scorecard/Cricsheet info.players.
    lineups = models.JSONField(default=dict, blank=True)
    strength = models.FloatField(default=1.0)
    external_id = models.CharField(max_length=60, blank=True, db_index=True)

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "matches"
<<<<<<< HEAD
        indexes = [models.Index(fields=["category", "date"], name="match_cat_date_idx")]
=======
>>>>>>> 32c894519d1d3703c8124559016ca18af8eb90d6

    def __str__(self):
        return f"{self.competition} {self.date}"


class Performance(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="performances")
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="performances")
    runs = models.PositiveIntegerField(default=0)
    balls = models.PositiveIntegerField(default=0)
    wickets = models.PositiveIntegerField(default=0)
    runs_conceded = models.PositiveIntegerField(default=0)
    overs = models.FloatField(default=0)
    opp_strength = models.FloatField(default=1.0)   # strength of the side he faced (internationals)
    # {"bat": {"pp": [runs, balls, outs], "mid": [...], "death": [...]},
    #  "bowl": {"pp": [conceded, legal_balls, wickets], ...}, "pos": batting position}
    # Empty for matches imported before phase tracking; see import_cricsheet --backfill-phases.
    phases = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("player", "match")
        ordering = ["-match__date"]

class CategoryValue(models.Model):
    """A player's value inside one tab, optionally inside one sub-selection (group)."""
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="cat_values")
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, db_index=True)
    group = models.CharField(max_length=30, blank=True, default="", db_index=True)  # "" = whole tab
    base_value = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    form_score = models.FloatField(default=50)
    form_premium = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    matches = models.PositiveIntegerField(default=0)
    tier = models.CharField(max_length=10, blank=True, default="", db_index=True)
    rating = models.FloatField(default=0)
    quality_score = models.FloatField(default=0, help_text="Long-term player quality, 0-100")
    potential_score = models.FloatField(default=50, help_text="Potential / upside indicator, 0-100")
    consistency_score = models.FloatField(default=0, help_text="Consistency indicator, 0-100")
    confidence_score = models.FloatField(default=0, help_text="Confidence in this estimate, 0-100")
    price_band = models.CharField(max_length=12, default="unrated", db_index=True)
    ceiling = models.FloatField(default=25)
    last_played = models.DateField(null=True, blank=True, db_index=True)
    locked = models.BooleanField(default=False, help_text="Keep my manual base value")

    class Meta:
        unique_together = ("player", "category", "group")

    @property
    def total(self):
        return self.base_value + self.form_premium

    @property
    def get_tier_display_name(self):
        return {"vip": "VIP", "balanced": "Balanced", "others": "Others"}.get(self.tier, "Unrated")

    @property
    def group_title(self):
        return group_title(self.group)

class AuctionMarketProfile(models.Model):
    """Configurable auction environment; purse and rules belong to a market, not a player."""
    MARKET_TYPES = [("IPL", "IPL-style league"), ("T20I", "International T20"),
                    ("ODI", "International ODI"), ("TEST", "International Test"),
                    ("DOMESTIC", "Domestic competition"), ("LEAGUE", "Other league"),
                    ("CUSTOM", "Custom market")]
    FORMATS = [("T20", "T20"), ("ODI", "ODI"), ("TEST", "Test")]
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True)
    market_type = models.CharField(max_length=12, choices=MARKET_TYPES, default="CUSTOM")
    cricket_format = models.CharField(max_length=4, choices=FORMATS, default="T20")
    source_category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, blank=True, default="")
    source_group = models.CharField(max_length=30, blank=True, default="", help_text="Optional league/domestic group, e.g. ipl or bbl.")
    team_purse = models.DecimalField(max_digits=9, decimal_places=2, default=100)
    squad_size = models.PositiveSmallIntegerField(default=20)
    team_count = models.PositiveSmallIntegerField(default=10)
    overseas_limit = models.PositiveSmallIntegerField(null=True, blank=True)
    market_factor = models.FloatField(default=1.0, help_text="Competition-level adjustment, normally 0.75-1.25.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} (₹{self.team_purse} Cr)"


class MarketValuation(models.Model):
    """A player's estimate inside one configured auction market."""
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="market_valuations")
    market = models.ForeignKey(AuctionMarketProfile, on_delete=models.CASCADE, related_name="valuations")
    category_value = models.ForeignKey(CategoryValue, on_delete=models.SET_NULL, null=True, blank=True, related_name="market_valuations")
    global_base_value = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    market_adjustment = models.FloatField(default=1.0)
    estimated_value = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    confidence_score = models.FloatField(default=0)
    price_band = models.CharField(max_length=12, default="value")
    explanation = models.JSONField(default=dict, blank=True)
    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("player", "market"),)
        ordering = ["-estimated_value", "player__name"]

    def __str__(self):
        return f"{self.player} · {self.market}: ₹{self.estimated_value} Cr"
