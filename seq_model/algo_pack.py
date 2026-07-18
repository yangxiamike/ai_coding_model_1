import torch
import os
import pandas as pd
import cloudpickle


def save_to_fold(
    path: str, 
    model: torch.nn.Module, 
    feature_function: callable,
    preprocess_function: callable
) -> None:
    os.makedirs(path, exist_ok=True)
    torch.save(model, os.path.join(path, 'model.pt'))
    with open(os.path.join(path, 'feature_function.pkl'), 'wb') as f:
        cloudpickle.dump(feature_function, f)
    with open(os.path.join(path, 'preprocess_function.pkl'), 'wb') as f:
        cloudpickle.dump(preprocess_function, f)


def load_from_fold(path: str):
    with open(os.path.join(path, 'feature_function.pkl'), 'rb') as f:
        feature_function = cloudpickle.load(f)
    with open(os.path.join(path, 'preprocess_function.pkl'), 'rb') as f:
        preprocess_function = cloudpickle.load(f)
    return torch.load(os.path.join(path, 'model.pt'), map_location='cpu'), feature_function, preprocess_function
