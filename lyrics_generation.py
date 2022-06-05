# -*- coding: utf-8 -*-
"""Lyrics generation.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1q_zpSPkZMZY7aGFjSeuE6gO3O16n-f-P

# Lyrics Generation with LSTM

## Installing and import libraries
"""

!pip install language_tool_python
!pip install better_profanity

# Imports
import random
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.backends.cudnn as cudnn; cudnn.benchmark = True
import language_tool_python as Language
from better_profanity import profanity as Profanity
import matplotlib.pyplot as plt

"""## Dataset and data processing"""

!gdown --id 1r4bDtZ_1CPLhlazYq6ccYolAN9cpG-ZD

# Options
data_path = "kanye_verses.txt"
batch_size = 16
batch_seq_len = 32
embed_size = 1024
rnn_size = 2048
drop_prob = 0.3

# Load data
with open(data_path) as f:
    text = f.read()

### Replace punctuation with tokens ###
# Create token dictionary
token_dict = {".": "|fullstop|",
              ",": "|comma|",
              "\"": "|quote|",
              ";": "|semicolon|",
              "!": "|exclamation|",
              "?": "|question|",
              "(": "|leftparen|",
              ")": "|rightparen|",
              "--": "|dash|",
              "\n": "|newline|"
}
# Replace punctuation
for punct, token in token_dict.items():
    text = text.replace(punct, f' {token} ')

#Print sample
text[:200]

### Compute vocabulary ###

# Split words
words = text.split(" ")
# Remove empty words
words = [word for word in words if len(word) > 0]
# Remove duplicates
vocab = list(set(words))

for i, w in enumerate(vocab[:5]):
  print(i, w)

# Create maps between words
vocab_to_int = {word: i for i,word in enumerate(vocab)}
int_to_vocab = {i: word for i,word in enumerate(vocab)}

# Compute number of words
num_words = len(vocab)
print(num_words)

print(len([word for word in text.split(" ") if len(word) > 0]))

text[200:]

# Convert text to ints
text_ints = [vocab_to_int[word] for word in text.split(" ") if len(word) > 0]

len(text_ints)

# Estimate average scene length
num_songs = len(text.split("|newline|  |newline|"))
print(len(text_ints)/num_songs)

print((len(text_ints)/num_songs)//batch_seq_len)

num_songs

print(batch_seq_len*((len(text_ints)/num_songs)//batch_seq_len))

splitteddf = text.split("|newline|  |newline|")

new_text = [word for word in text.split(" ") if len(word) > 0]
inputs = new_text[:5]
target = new_text[1:5]

print(inputs)
print(target)

# Set scene length (should be multiple of batch_seq_len)
song_length = 160

"""### Batch structure definition"""

# Compute batches
# Needs to be a function so we can compute different batches at different epochs
def get_batches(text_ints, song_length, batch_size, batch_seq_len):
    # Compute number of "songs"
    num_songs = len(text_ints)//song_length
    # Compute targets for each word (with fake target for final word)
    text_targets = text_ints[1:] + [text_ints[0]]
    # Split text into songs (input and targets)
    songs_inputs = [text_ints[i * song_length : (i+1) * song_length] for i in range(num_songs)]
    songs_targets = [text_targets[i*song_length:(i+1)*song_length] for i in range(num_songs)]
    # Split songs into mini-sequences of length batch_seq_len
    num_mini_sequences = song_length//batch_seq_len
    songs_inputs = [[song[i*batch_seq_len:(i+1)*batch_seq_len] for i in range(num_mini_sequences)] for song in songs_inputs]
    songs_targets = [[song[i*batch_seq_len:(i+1)*batch_seq_len] for i in range(num_mini_sequences)] for song in songs_targets]
    # Build batches
    num_batch_groups = len(songs_inputs)//batch_size
    batches = []
    for i in range(num_batch_groups):
        # Get the songs in this group
        group_songs_inputs = songs_inputs[i*batch_size:(i+1)*batch_size]
        group_songs_targets = songs_targets[i*batch_size:(i+1)*batch_size]
        # Build batches for each mini-sequence
        for j in range(num_mini_sequences):
            reset_state = (j == 0)
            batch_inputs = torch.LongTensor([group_songs_inputs[k][j] for k in range(batch_size)])
            batch_targets = torch.LongTensor([group_songs_targets[k][j] for k in range(batch_size)])
            batches.append((reset_state, batch_inputs, batch_targets))
    # Return
    return batches

# Get batches
batches = get_batches(text_ints, song_length, batch_size, batch_seq_len)
batches[0][1].shape

lyric = [  int_to_vocab[y.item()] for y in [x for x in batches[1][1][3]] ]
lyric

"""## Model definition

### Without ReLU
"""

# Define model
class Model(nn.Module):
    
    # Constructor
    def __init__(self, num_words, embed_size, drop_prob, rnn_size):
        # Call parent constructor
        super().__init__()
        # Store needed attributes
        self.rnn_size = rnn_size
        self.state = None
        # Define modules
        self.embedding = nn.Embedding(num_words, embed_size)
        self.rnn = nn.LSTM(embed_size, rnn_size, dropout = drop_prob, batch_first=True)
        self.decoder = nn.Linear(rnn_size, num_words)
        # Flags
        self.reset_next_state = False
        
    def reset_state(self):
        # Mark next state to be re-initialized
        self.reset_next_state = True
        
    def forward(self, x):
        # Check state reset
        if self.reset_next_state:
            # Initialize state (num_layers x batch_size x rnn_size)
            self.state = (
                x.new_zeros(1, x.size(0), self.rnn_size).float(), 
                x.new_zeros(1, x.size(0), self.rnn_size).float())
            # Clear flag
            self.reset_next_state = False
        # Embed data
        x = self.embedding(x)
        # Process RNN
        state = self.state if self.state is not None else None
        x, state = self.rnn(x, state)
        self.state = (state[0].data, state[1].data)
        # Compute outputs
        x = self.decoder(x)
        return x

# Create model
model = Model(num_words, embed_size, drop_prob, rnn_size)

# Setup device
dev = torch.device("cuda")

# Move model to device
model = model.to(dev)

# Define song generation function
def generate_lyric(model, seq_len, song_start):
    # Convert punctuaction in song start
    for punct, token in token_dict.items():
        song_start = song_start.replace(punct, f' {token} ')
    # Convert song start text to ints
    song_start = [vocab_to_int[word] for word in song_start.split(" ") if len(word) > 0]
    # Initialize output words/tokens
    lyric = song_start[:]
    # Convert script start to tensor (BxS = 1xS)
    song_start = torch.LongTensor(song_start).unsqueeze_(0)
    # Process script start and generate the rest of the script
    model.eval()
    model.reset_state()
    input = song_start
    for i in range(seq_len - song_start.size(1) + 1): # we include song_start as one of the generation steps
        # Copy input to device
        input = input.to(dev)
        # Pass to model
        output = model(input) # 1xSxV
        # Convert to word indexes
        words = output.max(2)[1] # 1xS
        words = words[0] # S
        # Add each word to song
        for j in range(words.size(0)):
            lyric.append(words[j].item())
        # Prepare next input
        input = torch.LongTensor([words[-1]]).unsqueeze(0) # 1xS = 1x1
    # Convert word indexes to text
    lyric = ' '.join([int_to_vocab[x] for x in lyric])
    # Convert punctuation tokens to symbols
    for punct,token in token_dict.items():
        lyric = lyric.replace(f"{token}", punct)
    # Return
    return lyric

generate_lyric(model, 160, "Hi people")

# Create optimizer
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

"""## Training"""

from tqdm.notebook import tqdm

# Initialize training history
loss_history = []
# Start training
for epoch in range(20):
    # Initialize accumulators for computing average loss/accuracy
    epoch_loss_sum = 0
    epoch_loss_cnt = 0
    # Set network mode
    model.train()
    # Process all batches
    for i,batch in enumerate(batches):
        # Parse batch
        reset_state, input, target = batch
        # Check reset state
        if reset_state:
            model.reset_state()
        # Move to device
        input = input.to(dev)
        target = target.to(dev)
        # Forward
        output = model(input)
        # Compute loss
        output = output.view(-1, num_words)
        target = target.view(-1)
        loss = F.cross_entropy(output, target)
        # Update loss sum
        epoch_loss_sum += loss.item()
        epoch_loss_cnt += 1
        # Backward and optimize
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    # Shift sequence and recompute batches
    shift_point = random.randint(1, len(text_ints)-1)
    text_ints = text_ints[:shift_point] + text_ints[shift_point:]
    batches = get_batches(text_ints, song_length, batch_size, batch_seq_len)
    # Epoch end - compute average epoch loss
    avg_loss = epoch_loss_sum/epoch_loss_cnt
    print(f"Epoch: {epoch+1}, loss: {epoch_loss_sum/epoch_loss_cnt:.4f}")
    print("Test sample:")
    print("---------------------------------------------------------------")
    print(generate_lyric(model, song_length, "Hi people"))
    print("---------------------------------------------------------------")
    # Add to histories
    loss_history.append(avg_loss)

# Plot loss
plt.title("Loss per epochs")
plt.ylabel('Loss')
plt.xlabel('Epochs')
plt.plot(loss_history)
plt.show()

withoutrelu = model



"""### Witht ReLU"""

# Define model
class Model(nn.Module):
    
    # Constructor
    def __init__(self, num_words, embed_size, drop_prob, rnn_size):
        # Call parent constructor
        super().__init__()
        # Store needed attributes
        self.rnn_size = rnn_size
        self.state = None
        # Define modules
        self.embedding = nn.Embedding(num_words, embed_size)
        self.rnn = nn.LSTM(embed_size, rnn_size, dropout = drop_prob, batch_first=True)
        self.relu = nn.ReLU()
        self.decoder = nn.Linear(rnn_size, num_words)
        # Flags
        self.reset_next_state = False
        
    def reset_state(self):
        # Mark next state to be re-initialized
        self.reset_next_state = True
        
    def forward(self, x):
        # Check state reset
        if self.reset_next_state:
            # Initialize state (num_layers x batch_size x rnn_size)
            self.state = (
                x.new_zeros(1, x.size(0), self.rnn_size).float(), 
                x.new_zeros(1, x.size(0), self.rnn_size).float())
            # Clear flag
            self.reset_next_state = False
        # Embed data
        x = self.embedding(x)
        # Process RNN
        state = self.state if self.state is not None else None
        x, state = self.rnn(x, state)
        x = self.relu(x)
        self.state = (state[0].data, state[1].data)
        # Compute outputs
        x = self.decoder(x)
        return x

# Create model
model = Model(num_words, embed_size, drop_prob, rnn_size)

# Setup device
dev = torch.device("cuda")

# Move model to device
model = model.to(dev)

# Create optimizer
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

from tqdm.notebook import tqdm

# Initialize training history
loss_history = []
# Start training
for epoch in range(20):
    # Initialize accumulators for computing average loss/accuracy
    epoch_loss_sum = 0
    epoch_loss_cnt = 0
    # Set network mode
    model.train()
    # Process all batches
    for i,batch in enumerate(batches):
        # Parse batch
        reset_state, input, target = batch
        # Check reset state
        if reset_state:
            model.reset_state()
        # Move to device
        input = input.to(dev)
        target = target.to(dev)
        # Forward
        output = model(input)
        # Compute loss
        output = output.view(-1, num_words)
        target = target.view(-1)
        loss = F.cross_entropy(output, target)
        # Update loss sum
        epoch_loss_sum += loss.item()
        epoch_loss_cnt += 1
        # Backward and optimize
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    # Shift sequence and recompute batches
    shift_point = random.randint(1, len(text_ints)-1)
    text_ints = text_ints[:shift_point] + text_ints[shift_point:]
    batches = get_batches(text_ints, song_length, batch_size, batch_seq_len)
    # Epoch end - compute average epoch loss
    avg_loss = epoch_loss_sum/epoch_loss_cnt
    print(f"Epoch: {epoch+1}, loss: {epoch_loss_sum/epoch_loss_cnt:.4f}")
    print("Test sample:")
    print("---------------------------------------------------------------")
    print(generate_lyric(model, song_length, "Hi people"))
    print("---------------------------------------------------------------")
    # Add to histories
    loss_history.append(avg_loss)

# Plot loss
plt.title("Loss per epochs")
plt.ylabel('Loss')
plt.xlabel('Epochs')
plt.plot(loss_history)
plt.show()

withrelu = model

"""## Output"""

# load the swear words to censor
Profanity.load_censor_words()

# create a tool for language checking
lang_tool = Language.LanguageTool('en-US')

def get_lyric(model, start_text, censor, num_words):
    
    # generate the text
    generated_text = generate_lyric(model, num_words, start_text.lower())
    
    # find all grammatial errors
    errors = lang_tool.check(generated_text)
    
    # create the corrected text
    corrected_text = Language.utils.correct(generated_text, errors)
    
    # censors the word if necessary
    return Profanity.censor(corrected_text) if censor else corrected_text

print(get_lyric(withoutrelu,"What you want to do", True, song_length))

print(get_lyric(withrelu,"What you want to do", True, song_length))