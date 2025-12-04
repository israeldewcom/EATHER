import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
import asyncio
import json
import numpy as np
from openai import AsyncOpenAI, OpenAI
import anthropic
import cohere
from tenacity import retry, stop_after_attempt, wait_exponential
import redis
import pickle

from app.core.config import settings
from app.database import get_db, redis_client
from app.models.transaction import Transaction
from app.models.document import Document
from app.models.ai import AIModel, AIResult

logger = logging.getLogger(__name__)

class AIService:
    """Complete AI service with multiple providers and caching"""
    
    def __init__(self):
        self.openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None
        self.anthropic_client = anthropic.Client(api_key=settings.ANTHROPIC_API_KEY) if settings.ANTHROPIC_API_KEY else None
        self.cohere_client = cohere.Client(api_key=settings.COHERE_API_KEY) if settings.COHERE_API_KEY else None
        
        self.cache = redis_client
        self.cache_prefix = "ai:"
        self.cache_ttl = 3600  # 1 hour
        
        # Load local ML models
        self.local_models = self.load_local_models()
        
    def load_local_models(self) -> Dict[str, Any]:
        """Load local ML models"""
        models = {}
        try:
            # Load category classifier
            import joblib
            models['category_classifier'] = joblib.load('ml/models/category_classifier.pkl')
            models['vectorizer'] = joblib.load('ml/models/tfidf_vectorizer.pkl')
            logger.info("Local ML models loaded successfully")
        except Exception as e:
            logger.warning(f"Failed to load local models: {e}")
        return models
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def categorize_transaction(self, transaction_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Categorize transaction using ensemble AI approach"""
        cache_key = f"{self.cache_prefix}categorize:{user_id}:{hash(str(transaction_data))}"
        
        # Check cache
        if settings.CACHE_ENABLED:
            cached = await self.cache.get(cache_key)
            if cached:
                return pickle.loads(cached)
        
        # Prepare inputs
        description = transaction_data.get('description', '')
        merchant = transaction_data.get('merchant', '')
        amount = transaction_data.get('amount')
        
        # Get results from multiple sources
        results = []
        
        # 1. Local ML model
        local_result = self._categorize_local(description, merchant)
        if local_result:
            results.append(local_result)
        
        # 2. OpenAI
        if self.openai_client:
            try:
                openai_result = await self._categorize_openai(description, merchant, amount)
                results.append(openai_result)
            except Exception as e:
                logger.error(f"OpenAI categorization failed: {e}")
        
        # 3. Anthropic
        if self.anthropic_client:
            try:
                anthropic_result = await self._categorize_anthropic(description, merchant, amount)
                results.append(anthropic_result)
            except Exception as e:
                logger.error(f"Anthropic categorization failed: {e}")
        
        # 4. Cohere
        if self.cohere_client:
            try:
                cohere_result = await self._categorize_cohere(description, merchant)
                results.append(cohere_result)
            except Exception as e:
                logger.error(f"Cohere categorization failed: {e}")
        
        # Ensemble voting
        final_category, confidence = self._ensemble_vote(results)
        
        # Get subcategory and tax info
        subcategory = self._get_subcategory(final_category, description)
        tax_info = self._get_tax_info(final_category, amount, user_id)
        
        result = {
            "category": final_category,
            "subcategory": subcategory,
            "confidence": confidence,
            "tax_deductible": tax_info.get('deductible', False),
            "tax_rate": tax_info.get('rate', 0.0),
            "suggested_account": self._get_suggested_account(final_category),
            "needs_review": confidence < 0.8,
            "sources": results
        }
        
        # Cache result
        if settings.CACHE_ENABLED:
            await self.cache.setex(cache_key, self.cache_ttl, pickle.dumps(result))
        
        # Save to database
        await self._save_ai_result(user_id, "categorization", result, transaction_data)
        
        return result
    
    def _categorize_local(self, description: str, merchant: str) -> Dict[str, Any]:
        """Categorize using local ML model"""
        if 'category_classifier' not in self.local_models:
            return None
        
        try:
            # Prepare text
            text = f"{description} {merchant}".strip()
            if not text:
                return None
            
            # Vectorize
            vector = self.local_models['vectorizer'].transform([text])
            
            # Predict
            prediction = self.local_models['category_classifier'].predict_proba(vector)[0]
            predicted_idx = np.argmax(prediction)
            confidence = prediction[predicted_idx]
            
            # Get category names
            categories = self.local_models['category_classifier'].classes_
            category = categories[predicted_idx]
            
            return {
                "provider": "local_ml",
                "category": category,
                "confidence": float(confidence),
                "model": "category_classifier"
            }
        except Exception as e:
            logger.error(f"Local model categorization failed: {e}")
            return None
    
    async def _categorize_openai(self, description: str, merchant: str, amount: float = None) -> Dict[str, Any]:
        """Categorize using OpenAI"""
        prompt = f"""
        Analyze this business transaction and categorize it:
        
        Description: {description}
        Merchant: {merchant}
        Amount: ${amount if amount else 'N/A'}
        
        Choose from these categories:
        1. meals - Restaurant, food, coffee, business meals
        2. travel - Flights, hotels, transportation
        3. office - Office supplies, equipment, software
        4. advertising - Marketing, ads, promotions
        5. subscriptions - SaaS, software subscriptions
        6. utilities - Electricity, internet, phone
        7. professional - Legal, accounting, consulting
        8. shipping - Postage, delivery, shipping
        9. insurance - Business insurance
        10. maintenance - Repairs, maintenance
        11. payroll - Employee salaries, benefits
        12. rent - Office rent, equipment rental
        13. entertainment - Client entertainment
        14. education - Training, courses, books
        15. uncategorized - Unknown or other
        
        Also provide:
        - Tax deductible status (true/false)
        - Suggested subcategory
        - Confidence score (0-1)
        
        Return as JSON with keys: category, subcategory, tax_deductible, confidence, reasoning
        """
        
        response = await self.openai_client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "You are a financial categorization expert. Return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        result["provider"] = "openai"
        
        return result
    
    async def _categorize_anthropic(self, description: str, merchant: str, amount: float = None) -> Dict[str, Any]:
        """Categorize using Anthropic Claude"""
        prompt = f"""
        Human: Categorize this business transaction:
        Description: {description}
        Merchant: {merchant}
        Amount: ${amount if amount else 'N/A'}
        
        Categories: meals, travel, office, advertising, subscriptions, utilities, professional, shipping, insurance, maintenance, payroll, rent, entertainment, education, uncategorized
        
        Return JSON with: category, subcategory, tax_deductible, confidence
        
        Assistant: {{
        """
        
        response = self.anthropic_client.completions.create(
            model="claude-2",
            prompt=prompt,
            max_tokens_to_sample=300,
            temperature=0.1,
        )
        
        # Parse response (Claude doesn't have native JSON mode)
        content = response.completion.strip()
        try:
            result = json.loads(content + "}")
        except:
            # Fallback parsing
            result = {
                "category": "uncategorized",
                "subcategory": None,
                "tax_deductible": False,
                "confidence": 0.5
            }
        
        result["provider"] = "anthropic"
        return result
    
    async def _categorize_cohere(self, description: str, merchant: str) -> Dict[str, Any]:
        """Categorize using Cohere"""
        text = f"{description} from {merchant}" if merchant else description
        
        response = self.cohere_client.classify(
            inputs=[text],
            model="embed-english-v2.0",
            preset="financial-categories"
        )
        
        if response.classifications:
            classification = response.classifications[0]
            result = {
                "provider": "cohere",
                "category": classification.prediction,
                "confidence": float(classification.confidence),
                "labels": classification.labels
            }
            return result
        
        return None
    
    def _ensemble_vote(self, results: List[Dict[str, Any]]) -> Tuple[str, float]:
        """Combine multiple AI predictions using weighted voting"""
        if not results:
            return "uncategorized", 0.0
        
        # Define provider weights
        weights = {
            "openai": 0.4,
            "anthropic": 0.3,
            "cohere": 0.2,
            "local_ml": 0.1
        }
        
        category_scores = {}
        
        for result in results:
            provider = result.get("provider")
            category = result.get("category")
            confidence = result.get("confidence", 0.5)
            
            if not category:
                continue
            
            weight = weights.get(provider, 0.1)
            score = confidence * weight
            
            if category in category_scores:
                category_scores[category] += score
            else:
                category_scores[category] = score
        
        if not category_scores:
            return "uncategorized", 0.0
        
        # Get best category
        best_category = max(category_scores.items(), key=lambda x: x[1])
        
        # Normalize confidence to 0-1
        total_score = sum(category_scores.values())
        normalized_confidence = best_category[1] / total_score if total_score > 0 else 0.0
        
        return best_category[0], normalized_confidence
    
    def _get_subcategory(self, category: str, description: str) -> str:
        """Get appropriate subcategory based on category and description"""
        subcategory_map = {
            "meals": ["business_lunch", "team_dinner", "coffee_meeting", "client_entertainment"],
            "travel": ["airfare", "hotel", "rental_car", "taxi", "meals_per_diem"],
            "office": ["supplies", "equipment", "software", "furniture", "internet"],
            "advertising": ["digital_ads", "social_media", "print_ads", "seo", "influencer"],
            "subscriptions": ["saas", "cloud_services", "membership", "software"],
            "utilities": ["electricity", "water", "internet", "phone", "gas"],
            "professional": ["legal", "accounting", "consulting", "design"],
            "shipping": ["postage", "courier", "delivery", "packaging"],
            "insurance": ["liability", "health", "property", "workers_comp"],
            "maintenance": ["repairs", "cleaning", "equipment_service"],
            "payroll": ["salaries", "benefits", "bonuses", "contractors"],
            "rent": ["office_rent", "equipment_rental", "storage"],
            "entertainment": ["client_gifts", "event_tickets", "corporate_events"],
            "education": ["training", "courses", "books", "conferences"],
        }
        
        subcategories = subcategory_map.get(category, [])
        if not subcategories:
            return None
        
        # Simple keyword matching for subcategory
        desc_lower = description.lower()
        for subcat in subcategories:
            if any(keyword in desc_lower for keyword in subcat.split('_')):
                return subcat
        
        return subcategories[0]  # Default first subcategory
    
    def _get_tax_info(self, category: str, amount: float, user_id: str) -> Dict[str, Any]:
        """Get tax information for category"""
        # This would normally come from tax rules database
        tax_rules = {
            "meals": {"deductible": True, "rate": 0.5, "limit": None},
            "travel": {"deductible": True, "rate": 1.0, "limit": None},
            "office": {"deductible": True, "rate": 1.0, "limit": None},
            "advertising": {"deductible": True, "rate": 1.0, "limit": None},
            "subscriptions": {"deductible": True, "rate": 1.0, "limit": None},
            "utilities": {"deductible": True, "rate": 1.0, "limit": None},
            "professional": {"deductible": True, "rate": 1.0, "limit": None},
            "shipping": {"deductible": True, "rate": 1.0, "limit": None},
            "insurance": {"deductible": True, "rate": 1.0, "limit": None},
            "maintenance": {"deductible": True, "rate": 1.0, "limit": None},
            "payroll": {"deductible": True, "rate": 1.0, "limit": None},
            "rent": {"deductible": True, "rate": 1.0, "limit": None},
            "entertainment": {"deductible": False, "rate": 0.0, "limit": None},
            "education": {"deductible": True, "rate": 1.0, "limit": 5250},
            "uncategorized": {"deductible": False, "rate": 0.0, "limit": None},
        }
        
        return tax_rules.get(category, {"deductible": False, "rate": 0.0, "limit": None})
    
    def _get_suggested_account(self, category: str) -> str:
        """Get suggested GL account for category"""
        account_map = {
            "meals": "6060 - Meals & Entertainment",
            "travel": "6070 - Travel Expenses",
            "office": "6010 - Office Expenses",
            "advertising": "6020 - Advertising",
            "subscriptions": "6030 - Software & Subscriptions",
            "utilities": "6040 - Utilities",
            "professional": "6050 - Professional Fees",
            "shipping": "6080 - Shipping & Delivery",
            "insurance": "6090 - Insurance",
            "maintenance": "6100 - Repairs & Maintenance",
            "payroll": "5010 - Salaries & Wages",
            "rent": "6110 - Rent Expense",
            "entertainment": "6120 - Entertainment",
            "education": "6130 - Training & Education",
            "uncategorized": "6999 - Miscellaneous Expense",
        }
        
        return account_map.get(category, "6999 - Miscellaneous Expense")
    
    async def _save_ai_result(self, user_id: str, task_type: str, result: Dict[str, Any], input_data: Dict[str, Any]):
        """Save AI result to database"""
        from app.database import SessionLocal
        
        db = SessionLocal()
        try:
            ai_result = AIResult(
                id=str(uuid.uuid4()),
                user_id=user_id,
                task_type=task_type,
                input_data=json.dumps(input_data),
                output_data=json.dumps(result),
                model_used="ensemble",
                confidence=result.get("confidence", 0.0),
                cost_estimated=0.001,  # Estimate cost
                processing_time=0.5,  # Estimate time
                created_at=datetime.utcnow()
            )
            
            db.add(ai_result)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to save AI result: {e}")
            db.rollback()
        finally:
            db.close()
    
    # Additional AI methods
    
    async def predict_cash_flow(self, user_id: str, months: int = 6) -> Dict[str, Any]:
        """Predict cash flow for next months"""
        # This would use historical data and ML for prediction
        from app.services.analytics_service import AnalyticsService
        analytics = AnalyticsService()
        
        historical = await analytics.get_financial_history(user_id, months * 30)
        
        # Simple prediction (replace with ML model)
        predictions = []
        last_amount = historical[-1]['amount'] if historical else 0
        
        for i in range(months):
            # Simple linear regression prediction
            predicted = last_amount * (1 + 0.05 * (i + 1))  # 5% growth assumption
            predictions.append({
                "month": i + 1,
                "predicted_amount": predicted,
                "confidence": 0.7 - (i * 0.1),  # Decreasing confidence
                "factors": ["historical_trend", "seasonality", "growth_rate"]
            })
        
        return {
            "predictions": predictions,
            "historical_data": historical,
            "model_used": "linear_regression",
            "confidence_overall": 0.65
        }
    
    async def detect_anomalies(self, user_id: str) -> List[Dict[str, Any]]:
        """Detect anomalous transactions"""
        from app.database import SessionLocal
        
        db = SessionLocal()
        try:
            # Get recent transactions
            transactions = db.query(Transaction).filter(
                Transaction.user_id == user_id,
                Transaction.created_at >= datetime.utcnow() - timedelta(days=90)
            ).all()
            
            anomalies = []
            
            # Simple anomaly detection (replace with ML)
            for txn in transactions:
                amount = float(txn.amount)
                
                # Check for unusually large amounts
                if amount > 10000:
                    anomalies.append({
                        "transaction_id": txn.id,
                        "type": "large_amount",
                        "severity": "high",
                        "amount": amount,
                        "description": txn.description,
                        "reason": f"Unusually large transaction: ${amount:,.2f}"
                    })
                
                # Check for round amounts
                if amount % 1000 == 0 and amount >= 5000:
                    anomalies.append({
                        "transaction_id": txn.id,
                        "type": "round_amount",
                        "severity": "medium",
                        "amount": amount,
                        "description": txn.description,
                        "reason": f"Round amount transaction: ${amount:,.2f}"
                    })
            
            return anomalies
            
        finally:
            db.close()
    
    async def generate_financial_insights(self, user_id: str) -> Dict[str, Any]:
        """Generate financial insights using AI"""
        from app.services.analytics_service import AnalyticsService
        
        analytics = AnalyticsService()
        metrics = await analytics.get_financial_metrics(user_id)
        
        # Use AI to generate insights
        if self.openai_client:
            prompt = f"""
            Generate financial insights based on these metrics:
            
            Total Income: ${metrics.get('total_income', 0):,.2f}
            Total Expenses: ${metrics.get('total_expenses', 0):,.2f}
            Net Profit: ${metrics.get('net_profit', 0):,.2f}
            Top Categories: {metrics.get('top_categories', [])}
            Growth Rate: {metrics.get('growth_rate', 0):.1%}
            
            Provide:
            1. Key insights
            2. Recommendations
            3. Risk areas
            4. Opportunities
            
            Return as JSON.
            """
            
            response = await self.openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are a financial advisor. Provide actionable insights."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            return json.loads(response.choices[0].message.content)
        
        return {"insights": [], "recommendations": []}
    
    async def optimize_taxes(self, user_id: str, year: int = None) -> Dict[str, Any]:
        """Generate tax optimization suggestions"""
        from app.services.tax_service import TaxService
        
        tax_service = TaxService()
        tax_data = await tax_service.get_tax_summary(user_id, year)
        
        # Use AI to generate tax optimization suggestions
        if self.openai_client:
            prompt = f"""
            Analyze this tax data and provide optimization suggestions:
            
            Total Income: ${tax_data.get('total_income', 0):,.2f}
            Total Deductions: ${tax_data.get('total_deductions', 0):,.2f}
            Taxable Income: ${tax_data.get('taxable_income', 0):,.2f}
            Estimated Tax: ${tax_data.get('estimated_tax', 0):,.2f}
            
            Deductions by Category:
            {json.dumps(tax_data.get('deductions_by_category', {}), indent=2)}
            
            Provide:
            1. Potential additional deductions
            2. Tax-saving strategies
            3. Estimated savings potential
            4. Deadlines and requirements
            
            Return as JSON.
            """
            
            response = await self.openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are a tax optimization expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            return json.loads(response.choices[0].message.content)
        
        return {"suggestions": [], "estimated_savings": 0}
