# Import necessary libraries for data manipulation, machine learning, and serialization
import pandas as pd
import numpy as np
import pickle
import os
import yaml
import logging
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
from sklearn.model_selection import train_test_split, GridSearchCV, cross_val_score
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, AdaBoostClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score, precision_recall_curve, roc_curve, auc
from sklearn.preprocessing import StandardScaler
import joblib
from framer_motion import motion

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create a models directory if it doesn't exist
models_dir = "models"
if not os.path.exists(models_dir):
    os.makedirs(models_dir)

# Create a results directory for saving plots and metrics
results_dir = "model_evaluation"
if not os.path.exists(results_dir):
    os.makedirs(results_dir)

# Define the filenames
train_dataset_filename = "vehicle_data_train.csv"
val_dataset_filename = "vehicle_data_val.csv"
full_dataset_filename = "vehicle_data.csv"
metadata_filename = "dataset_metadata.yaml"

def load_data():
    """Load and prepare the dataset for training"""
    try:
        # Load metadata if available
        if os.path.exists(metadata_filename):
            with open(metadata_filename, 'r') as file:
                metadata = yaml.safe_load(file)
                logger.info(f"Dataset metadata loaded from '{metadata_filename}'")
                logger.info(f"Dataset version: {metadata.get('version', 'unknown')}")
        
        # Check if we have train/val split files
        if os.path.exists(train_dataset_filename) and os.path.exists(val_dataset_filename):
            train_df = pd.read_csv(train_dataset_filename)
            val_df = pd.read_csv(val_dataset_filename)
            logger.info(f"Train dataset '{train_dataset_filename}' loaded with {len(train_df)} rows.")
            logger.info(f"Validation dataset '{val_dataset_filename}' loaded with {len(val_df)} rows.")
            return train_df, val_df, None  # No need to split
        
        # If not, load the full dataset and create a split
        elif os.path.exists(full_dataset_filename):
            df = pd.read_csv(full_dataset_filename)
            logger.info(f"Full dataset '{full_dataset_filename}' loaded with {len(df)} rows.")
            
            # Split dataset 80/20
            train_df, val_df = train_test_split(df, test_size=0.2, random_state=42)
            logger.info(f"Dataset split: {len(train_df)} training samples, {len(val_df)} validation samples")
            return train_df, val_df, df
        
        else:
            logger.error(f"No dataset files found. Run generate_dataset.py first.")
            exit(1)
            
    except Exception as e:
        logger.error(f"Error loading dataset: {e}")
        exit(1)

def prepare_features(train_df, val_df=None):
    """Prepare features for model training"""
    # Identity categorical and numerical features
    if os.path.exists(metadata_filename):
        with open(metadata_filename, 'r') as file:
            metadata = yaml.safe_load(file)
            categorical_features = metadata['features']['categorical']
            # Use only basic features for prediction to avoid data leakage
            target = metadata['features']['target']
    else:
        # Default feature types if metadata is not available
        categorical_features = ["vehicle_type", "region", "road_condition", "weather"]
        target = "overload_status"
    
    logger.info(f"Categorical features: {categorical_features}")
    
    # Use one-hot encoded features if they exist in the dataset
    # These are features like "vehicle_type_2-wheeler" that were created during data generation
    one_hot_cols = [col for col in train_df.columns if any(col.startswith(f"{feat}_") for feat in categorical_features)]
    
    # Determine features to use - prioritize existing scaled features, then add one-hot encoded categorical features
    scaled_features = [col for col in train_df.columns if col.endswith("_scaled")]
    
    # If no scaled features, use original numerical features
    if not scaled_features:
        numerical_features = [col for col in train_df.columns 
                             if col not in categorical_features + [target] 
                             and not any(col.startswith(f"{feat}_") for feat in categorical_features)]
        
        # Define feature list - exclude categorical features to avoid duplication with one-hot features
        features = numerical_features + one_hot_cols
        
        # Create scaler for numerical features
        scaler = StandardScaler()
        
        # Process training data
        X_train = train_df[features].copy()
        X_train[numerical_features] = scaler.fit_transform(X_train[numerical_features])
        y_train = train_df[target]
        
        if val_df is not None:
            # Process validation data using same scaler
            X_val = val_df[features].copy()
            X_val[numerical_features] = scaler.transform(X_val[numerical_features])
            y_val = val_df[target]
        else:
            X_val, y_val = None, None
            
        # Save the scaler
        with open("vehicle_load_scaler.pkl", "wb") as file:
            pickle.dump(scaler, file)
            
    else:
        # Use pre-scaled features
        features = one_hot_cols + scaled_features
        
        # Process training data
        X_train = train_df[features]
        y_train = train_df[target]
        
        if val_df is not None:
            # Process validation data
            X_val = val_df[features]
            y_val = val_df[target]
        else:
            X_val, y_val = None, None
            
        scaler = None  # No need for a scaler as we're using pre-scaled features
    
    logger.info(f"Features used for training: {features}")
    logger.info(f"Target: {target}")
    
    # Save features list for later use
    with open(os.path.join(models_dir, "model_features.pkl"), "wb") as f:
        pickle.dump(features, f)
    
    return X_train, y_train, X_val, y_val, features, scaler

def train_models(X_train, y_train, X_val, y_val, features):
    """Train multiple models and select the best one"""
    models = {
        "random_forest": RandomForestClassifier(random_state=42),
        "gradient_boosting": GradientBoostingClassifier(random_state=42),
        "ada_boost": AdaBoostClassifier(random_state=42),
        "mlp": MLPClassifier(random_state=42),
        "svm": SVC(probability=True, random_state=42)
    }
    
    # Define parameter grids for GridSearchCV - simplified for faster execution
    param_grids = {
        "random_forest": {
            'n_estimators': [100, 200],
            'max_depth': [10, 20, None],
            'min_samples_split': [2, 5]
        },
        "gradient_boosting": {
            'n_estimators': [100, 200],
            'learning_rate': [0.01, 0.1],
            'max_depth': [3, 5]
        },
        "ada_boost": {
            'n_estimators': [50, 100],
            'learning_rate': [0.1, 1.0]
        },
        "mlp": {
            'hidden_layer_sizes': [(50,), (100,)],
            'activation': ['relu', 'tanh'],
            'alpha': [0.001, 0.01]
        },
        "svm": {
            'C': [1, 10],
            'kernel': ['rbf'],
            'gamma': ['scale']
        }
    }
    
    results = {}
    best_model_name = None
    best_model = None
    best_score = 0
    
    for model_name, model in models.items():
        logger.info(f"Training {model_name} model...")
        
        # Use GridSearchCV to find the best parameters
        grid_search = GridSearchCV(
            estimator=model, 
            param_grid=param_grids[model_name],
            cv=3,  # 3-fold cross-validation
            n_jobs=-1,  # Use all cores
            scoring='accuracy',
            verbose=1
        )
        
        # Fit the grid search to the data
        grid_search.fit(X_train, y_train)
        
        # Get the best model
        best_params = grid_search.best_params_
        logger.info(f"Best parameters for {model_name}: {best_params}")
        
        # Create model with best parameters
        if model_name == "random_forest":
            model = RandomForestClassifier(random_state=42, **best_params)
        elif model_name == "gradient_boosting":
            model = GradientBoostingClassifier(random_state=42, **best_params)
        elif model_name == "ada_boost":
            model = AdaBoostClassifier(random_state=42, **best_params)
        elif model_name == "mlp":
            model = MLPClassifier(random_state=42, **best_params)
        elif model_name == "svm":
            model = SVC(probability=True, random_state=42, **best_params)
        
        # Fit the model to the training data
        model.fit(X_train, y_train)
        
        # Evaluate on validation set
        y_pred = model.predict(X_val)
        accuracy = accuracy_score(y_val, y_pred)
        logger.info(f"{model_name} accuracy: {accuracy:.4f}")
        
        # Save detailed classification report
        report = classification_report(y_val, y_pred, output_dict=True)
        
        # Calculate predictions probabilities for ROC curve
        if hasattr(model, "predict_proba"):
            y_proba = model.predict_proba(X_val)[:, 1]  # Probability of positive class
            
            # Calculate ROC curve and AUC
            fpr, tpr, _ = roc_curve(y_val == "Overloaded", y_proba)
            roc_auc = auc(fpr, tpr)
            
            # Plot ROC curve
            plt.figure(figsize=(8, 6))
            plt.plot(fpr, tpr, label=f'ROC curve (area = {roc_auc:.2f})')
            plt.plot([0, 1], [0, 1], 'k--')
            plt.xlim([0.0, 1.0])
            plt.ylim([0.0, 1.05])
            plt.xlabel('False Positive Rate')
            plt.ylabel('True Positive Rate')
            plt.title(f'ROC Curve - {model_name}')
            plt.legend(loc="lower right")
            plt.savefig(os.path.join(results_dir, f"{model_name}_roc_curve.png"))
            plt.close()
            
            # Plot confusion matrix
            cm = confusion_matrix(y_val, y_pred)
            plt.figure(figsize=(8, 6))
            sns.heatmap(cm, annot=True, fmt='d', cmap='Blues', 
                      xticklabels=["Not Overloaded", "Overloaded"],
                      yticklabels=["Not Overloaded", "Overloaded"])
            plt.xlabel('Predicted')
            plt.ylabel('Actual')
            plt.title(f'Confusion Matrix - {model_name}')
            plt.savefig(os.path.join(results_dir, f"{model_name}_confusion_matrix.png"))
            plt.close()
            
            # Feature importance for tree-based models
            if model_name in ["random_forest", "gradient_boosting", "ada_boost"]:
                feature_importances = model.feature_importances_
                indices = np.argsort(feature_importances)[-20:]  # Top 20 features
                
                # Plot feature importances
                plt.figure(figsize=(12, 8))
                plt.title(f"Top 20 Feature Importances - {model_name}")
                plt.barh(range(len(indices)), feature_importances[indices], align="center")
                plt.yticks(range(len(indices)), [features[i] for i in indices])
                plt.tight_layout()
                plt.savefig(os.path.join(results_dir, f"{model_name}_feature_importance.png"))
                plt.close()
        
        # Store results
        results[model_name] = {
            'model': model,
            'accuracy': accuracy,
            'report': report,
            'best_params': best_params,
        }
        
        # Track best model
        if accuracy > best_score:
            best_score = accuracy
            best_model_name = model_name
            best_model = model
    
    logger.info(f"Best performing model: {best_model_name} with accuracy {best_score:.4f}")
    
    # Save all models for later comparison
    for model_name, result in results.items():
        model_path = os.path.join(models_dir, f"{model_name}_model.pkl")
        with open(model_path, "wb") as file:
            pickle.dump(result['model'], file)
            
        # Save model metrics
        metrics_path = os.path.join(results_dir, f"{model_name}_metrics.yml")
        metrics = {
            'accuracy': float(result['accuracy']),
            'classification_report': {k: (v if isinstance(v, dict) else float(v)) 
                                     for k, v in result['report'].items()},
            'best_params': result['best_params'],
            'training_time': datetime.now().isoformat()
        }
        
        with open(metrics_path, 'w') as file:
            yaml.dump(metrics, file)
    
    # Save best model separately
    with open("vehicle_load_model.pkl", "wb") as file:
        pickle.dump(best_model, file)
        
    # Create comparison plot of all models
    accuracies = [results[model_name]['accuracy'] for model_name in models.keys()]
    plt.figure(figsize=(10, 6))
    plt.bar(models.keys(), accuracies)
    plt.title('Model Comparison')
    plt.ylabel('Validation Accuracy')
    plt.ylim(0, 1)
    plt.xticks(rotation=45)
    for i, v in enumerate(accuracies):
        plt.text(i, v + 0.01, f"{v:.4f}", ha='center')
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "model_comparison.png"))
    plt.close()
    
    return best_model, best_model_name

def main():
    logger.info("Starting model training process...")
    
    # Load data
    train_df, val_df, full_df = load_data()
    
    # Prepare features
    X_train, y_train, X_val, y_val, features, scaler = prepare_features(train_df, val_df)
    
    # Train and select the best model
    best_model, best_model_name = train_models(X_train, y_train, X_val, y_val, features)
    
    logger.info(f"Best model: {best_model_name}")
    logger.info(f"Model saved to 'vehicle_load_model.pkl'")
    if scaler:
        logger.info(f"Scaler saved to 'vehicle_load_scaler.pkl'")
    
    logger.info("Training complete.")

if __name__ == "__main__":
    main()
