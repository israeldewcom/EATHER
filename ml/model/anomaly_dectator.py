import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import LocalOutlierFactor
from sklearn.svm import OneClassSVM
import joblib
import json
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

class AnomalyDetector:
    """Advanced anomaly detection for financial transactions"""
    
    def __init__(self, model_path='ml/models/anomaly_detector.pkl'):
        self.model_path = model_path
        self.scaler_path = 'ml/models/anomaly_scaler.pkl'
        self.config_path = 'ml/models/anomaly_config.json'
        
        self.model = None
        self.scaler = None
        self.config = self.load_config()
        
    def load_config(self):
        """Load anomaly detection configuration"""
        default_config = {
            'contamination': 0.1,
            'features': ['amount', 'day_of_week', 'hour', 'amount_zscore', 'frequency'],
            'thresholds': {
                'high_amount': 10000,
                'frequency_threshold': 10,
                'time_variance_threshold': 3,
            },
            'weights': {
                'amount': 0.4,
                'time': 0.3,
                'frequency': 0.2,
                'pattern': 0.1,
            }
        }
        
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                return {**default_config, **config}
        except:
            return default_config
    
    def prepare_features(self, transactions):
        """Prepare features for anomaly detection"""
        df = pd.DataFrame(transactions)
        
        # Convert dates
        df['date'] = pd.to_datetime(df['transaction_date'])
        df['day_of_week'] = df['date'].dt.dayofweek
        df['hour'] = df['date'].dt.hour
        df['day_of_month'] = df['date'].dt.day
        
        # Calculate amount statistics
        df['amount_log'] = np.log1p(df['amount'].abs())
        df['amount_zscore'] = (df['amount'] - df['amount'].mean()) / df['amount'].std()
        
        # Calculate frequency features
        merchant_freq = df['merchant'].value_counts().to_dict()
        df['merchant_frequency'] = df['merchant'].map(merchant_freq)
        
        category_freq = df['category'].value_counts().to_dict()
        df['category_frequency'] = df['category'].map(category_freq)
        
        # Time-based features
        df['days_since_last'] = df.groupby('merchant')['date'].diff().dt.days
        df['time_variance'] = df.groupby('merchant')['hour'].transform('std')
        
        # Pattern features
        df['weekend'] = df['day_of_week'].isin([5, 6]).astype(int)
        df['business_hours'] = ((df['hour'] >= 9) & (df['hour'] <= 17)).astype(int)
        
        # Fill NaN values
        df = df.fillna(0)
        
        # Select features
        features = self.config['features']
        available_features = [f for f in features if f in df.columns]
        
        return df[available_features]
    
    def train(self, transactions, save=True):
        """Train anomaly detection model"""
        print("Training anomaly detection model...")
        
        # Prepare features
        X = self.prepare_features(transactions)
        
        # Scale features
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        # Train multiple models
        models = {
            'isolation_forest': IsolationForest(
                contamination=self.config['contamination'],
                random_state=42,
                n_estimators=100
            ),
            'local_outlier_factor': LocalOutlierFactor(
                contamination=self.config['contamination'],
                novelty=True
            ),
            'one_class_svm': OneClassSVM(
                nu=self.config['contamination'],
                kernel='rbf',
                gamma='auto'
            )
        }
        
        # Ensemble approach
        predictions = []
        for name, model in models.items():
            try:
                if name == 'local_outlier_factor':
                    # LOF needs to be fit without labels
                    model.fit(X_scaled)
                else:
                    model.fit(X_scaled)
                
                # Get predictions (-1 for anomalies, 1 for normal)
                if hasattr(model, 'predict'):
                    pred = model.predict(X_scaled)
                    predictions.append(pred)
                elif hasattr(model, 'fit_predict'):
                    pred = model.fit_predict(X_scaled)
                    predictions.append(pred)
            except Exception as e:
                print(f"Model {name} failed: {e}")
                continue
        
        # Combine predictions
        if predictions:
            # Vote by majority
            combined = np.sum(predictions, axis=0)
            final_predictions = np.where(combined < 0, -1, 1)
            
            # Use Isolation Forest as base model
            self.model = models['isolation_forest']
        else:
            # Fallback to Isolation Forest
            self.model = IsolationForest(
                contamination=self.config['contamination'],
                random_state=42
            )
            self.model.fit(X_scaled)
            final_predictions = self.model.predict(X_scaled)
        
        # Calculate anomaly scores
        if hasattr(self.model, 'decision_function'):
            scores = self.model.decision_function(X_scaled)
        elif hasattr(self.model, 'score_samples'):
            scores = self.model.score_samples(X_scaled)
        else:
            scores = final_predictions
        
        # Analyze results
        n_anomalies = sum(final_predictions == -1)
        print(f"Detected {n_anomalies} anomalies ({n_anomalies/len(transactions)*100:.1f}%)")
        
        # Save model
        if save:
            self.save_model()
        
        return {
            'predictions': final_predictions.tolist(),
            'scores': scores.tolist() if isinstance(scores, np.ndarray) else scores,
            'features': X.columns.tolist(),
            'n_anomalies': n_anomalies,
            'anomaly_rate': n_anomalies / len(transactions)
        }
    
    def detect(self, transactions):
        """Detect anomalies in transactions"""
        if not self.model or not self.scaler:
            self.load_model()
        
        # Prepare features
        X = self.prepare_features(transactions)
        
        # Scale features
        X_scaled = self.scaler.transform(X)
        
        # Predict anomalies
        predictions = self.model.predict(X_scaled)
        
        # Get anomaly scores
        if hasattr(self.model, 'decision_function'):
            scores = self.model.decision_function(X_scaled)
        elif hasattr(self.model, 'score_samples'):
            scores = self.model.score_samples(X_scaled)
        else:
            scores = predictions
        
        # Apply rule-based checks
        rule_based_anomalies = self._rule_based_detection(transactions)
        
        # Combine results
        anomalies = []
        for i, (pred, score) in enumerate(zip(predictions, scores)):
            transaction = transactions[i]
            
            # Check ML prediction
            is_ml_anomaly = pred == -1
            
            # Check rule-based
            rule_reasons = []
            for rule in rule_based_anomalies:
                if rule['index'] == i:
                    rule_reasons.append(rule['reason'])
            
            # Combine decision
            is_anomaly = is_ml_anomaly or len(rule_reasons) > 0
            
            if is_anomaly:
                anomaly = {
                    'transaction_id': transaction.get('id'),
                    'index': i,
                    'amount': float(transaction.get('amount', 0)),
                    'description': transaction.get('description', ''),
                    'merchant': transaction.get('merchant', ''),
                    'date': transaction.get('transaction_date'),
                    'ml_score': float(score) if isinstance(score, (np.ndarray, np.generic)) else float(score),
                    'ml_anomaly': is_ml_anomaly,
                    'rule_reasons': rule_reasons,
                    'severity': self._calculate_severity(
                        float(score) if isinstance(score, (np.ndarray, np.generic)) else float(score),
                        len(rule_reasons),
                        float(transaction.get('amount', 0))
                    ),
                    'suggested_action': self._get_suggested_action(
                        is_ml_anomaly,
                        rule_reasons,
                        float(transaction.get('amount', 0))
                    )
                }
                anomalies.append(anomaly)
        
        return anomalies
    
    def _rule_based_detection(self, transactions):
        """Rule-based anomaly detection"""
        anomalies = []
        thresholds = self.config['thresholds']
        
        for i, txn in enumerate(transactions):
            reasons = []
            
            # High amount check
            amount = float(txn.get('amount', 0))
            if abs(amount) > thresholds['high_amount']:
                reasons.append(f"High amount: ${amount:,.2f}")
            
            # Round amount check
            if amount % 1000 == 0 and abs(amount) >= 5000:
                reasons.append(f"Round amount: ${amount:,.2f}")
            
            # Unusual time check
            date_str = txn.get('transaction_date')
            if date_str:
                try:
                    date = pd.to_datetime(date_str)
                    if date.hour < 5 or date.hour > 22:  # Outside normal business hours
                        reasons.append(f"Unusual time: {date.hour}:00")
                    
                    if date.weekday() >= 5:  # Weekend
                        reasons.append("Weekend transaction")
                except:
                    pass
            
            # New merchant check
            merchant = txn.get('merchant', '')
            if merchant and 'new' in merchant.lower():
                reasons.append("New merchant")
            
            if reasons:
                anomalies.append({
                    'index': i,
                    'transaction_id': txn.get('id'),
                    'reasons': reasons
                })
        
        return anomalies
    
    def _calculate_severity(self, ml_score, rule_count, amount):
        """Calculate anomaly severity"""
        # Base severity from ML score
        if ml_score < -0.5:
            severity = 'high'
        elif ml_score < -0.2:
            severity = 'medium'
        else:
            severity = 'low'
        
        # Adjust based on rules
        if rule_count >= 2:
            severity = 'high'
        elif rule_count == 1 and severity == 'low':
            severity = 'medium'
        
        # Adjust based on amount
        if abs(amount) > 10000:
            severity = 'high'
        elif abs(amount) > 5000 and severity != 'high':
            severity = 'medium'
        
        return severity
    
    def _get_suggested_action(self, is_ml_anomaly, rule_reasons, amount):
        """Get suggested action for anomaly"""
        if 'High amount' in ' '.join(rule_reasons) or abs(amount) > 10000:
            return "Review immediately and verify with documentation"
        elif is_ml_anomaly and len(rule_reasons) > 0:
            return "Review and confirm with transaction party"
        elif is_ml_anomaly:
            return "Review categorization and confirm details"
        else:
            return "Monitor and review if pattern continues"
    
    def save_model(self):
        """Save model and scaler"""
        import os
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        
        joblib.dump(self.model, self.model_path)
        joblib.dump(self.scaler, self.scaler_path)
        
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
        
        print(f"Model saved to {self.model_path}")
    
    def load_model(self):
        """Load model and scaler"""
        try:
            if os.path.exists(self.model_path):
                self.model = joblib.load(self.model_path)
                self.scaler = joblib.load(self.scaler_path)
                print("Anomaly detection model loaded successfully")
                return True
        except Exception as e:
            print(f"Error loading model: {e}")
        
        return False
    
    def update_config(self, new_config):
        """Update model configuration"""
        self.config = {**self.config, **new_config}
        self.save_model()
    
    def get_feature_importance(self):
        """Get feature importance for anomalies"""
        if not self.model or not hasattr(self.model, 'feature_importances_'):
            return {}
        
        try:
            features = self.config['features']
            importances = self.model.feature_importances_
            
            return {
                feature: importance
                for feature, importance in zip(features, importances)
                if feature in features
            }
        except:
            return {}

# Training script
if __name__ == "__main__":
    # Generate sample data
    np.random.seed(42)
    n_samples = 1000
    
    transactions = []
    base_date = datetime.now() - timedelta(days=365)
    
    # Normal transactions
    for i in range(int(n_samples * 0.9)):
        date = base_date + timedelta(days=np.random.randint(0, 365))
        amount = np.random.lognormal(mean=5, sigma=1.5)
        
        transactions.append({
            'id': f'txn_{i}',
            'transaction_date': date.isoformat(),
            'amount': amount,
            'merchant': np.random.choice(['Amazon', 'Starbucks', 'Google', 'Microsoft', 'Uber']),
            'category': np.random.choice(['office', 'meals', 'travel', 'subscriptions']),
            'description': f'Purchase {i}'
        })
    
    # Anomalous transactions
    for i in range(int(n_samples * 0.1)):
        date = base_date + timedelta(days=np.random.randint(0, 365))
        # Make some anomalies at unusual times
        if np.random.random() > 0.5:
            date = date.replace(hour=np.random.choice([1, 2, 3, 4, 23]))
        
        # Make some with unusual amounts
        if np.random.random() > 0.5:
            amount = np.random.uniform(10000, 50000)
        else:
            amount = np.random.lognormal(mean=5, sigma=1.5)
        
        transactions.append({
            'id': f'txn_ano_{i}',
            'transaction_date': date.isoformat(),
            'amount': amount,
            'merchant': 'Unknown' if np.random.random() > 0.7 else np.random.choice(['Amazon', 'Starbucks']),
            'category': 'uncategorized',
            'description': f'Suspicious {i}'
        })
    
    # Train model
    detector = AnomalyDetector()
    results = detector.train(transactions, save=True)
    
    # Test detection
    test_transactions = transactions[:100]
    anomalies = detector.detect(test_transactions)
    
    print(f"\nDetected {len(anomalies)} anomalies in test set:")
    for anomaly in anomalies[:5]:  # Show first 5
        print(f"  - {anomaly['description']}: ${anomaly['amount']:,.2f} ({anomaly['severity']})")
