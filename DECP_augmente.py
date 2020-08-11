# -*- coding: utf-8 -*-
"""
Created on Mon Aug 10 
@author: Lucas GEFFARD
"""
######################### Importation des librairies ##########################
import pandas as pd
from pandas.io.json import json_normalize
import numpy as np
import json
import os

from lxml import html
import requests
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
import time

from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from scipy.cluster.hierarchy import dendrogram, linkage, fcluster

import matplotlib.pyplot as plt
import folium
from folium.plugins import MarkerCluster
from folium.plugins import HeatMap
######################################################################
#import warnings
#warnings.filterwarnings("ignore")
######################################################################
#Chargement des données
chemin = "H:/Desktop/MEF_dep"
os.chdir(chemin)
with open("dataJSON/decp.json", encoding='utf-8') as json_data:
    data = json.load(json_data)
df = json_normalize(data['marches']) #Aplatir les données Json imbriquées

#Gestion différences concessionnaires / titulaires
df.titulaires = np.where(df.titulaires.isnull(), df.concessionnaires, df.titulaires)
df.montant = np.where(df.montant.isnull(), df.valeurGlobale, df.montant)
df['acheteur.id'] = np.where(df['acheteur.id'].isnull(), df['autoriteConcedante.id'], df['acheteur.id'])
df['acheteur.nom'] = np.where(df['acheteur.nom'].isnull(), df['autoriteConcedante.nom'], df['acheteur.nom'])
donneesInutiles = ['dateSignature', 'dateDebutExecution',  'valeurGlobale', 'donneesExecution', 'concessionnaires', 
                   'montantSubventionPublique', 'modifications', 'autoriteConcedante.id', 'autoriteConcedante.nom']
df = df.drop(columns=donneesInutiles)

#Récupération des données titulaires    
df.titulaires.fillna('0', inplace=True)
dfO = df[df['titulaires'] == '0']
df = df[df['titulaires'] != '0']

def reorga(x):
    return pd.DataFrame.from_dict(x,orient='index').T

liste_col = []
for index, liste in enumerate(df.titulaires) :
    for i in liste :
        col = reorga(i)
        col["index"] = index
        liste_col.append(col)

df.reset_index(level=0, inplace=True)
del df['index']
df.reset_index(level=0, inplace=True) 
myList = list(df.columns); myList[0] = 'index'; df.columns = myList

dfTitulaires = pd.concat(liste_col, sort = False)
dfTitulaires.reset_index(level=0, inplace=True) 
myList = list(dfTitulaires.columns); myList[2] = 'idTitulaires'; dfTitulaires.columns = myList

df = pd.merge(df, dfTitulaires, on=['index'])
df = df.drop(columns=['titulaires','level_0'])
del i, index, liste, liste_col, col, dfTitulaires, myList, donneesInutiles

######################################################################
#...............    Nettoyage/formatage des données
################### Identifier et supprimer les doublons
df = df.drop_duplicates(subset=['source', '_type', 'nature', 'procedure', 'dureeMois',
                           'datePublicationDonnees', 'lieuExecution.code', 'lieuExecution.typeCode',
                           'lieuExecution.nom', 'id', 'objet', 'codeCPV', 'dateNotification', 'montant', 
                           'formePrix', 'acheteur.id', 'acheteur.nom', 'typeIdentifiant', 'idTitulaires',
                           'denominationSociale'], keep='first')
df.reset_index(inplace=True, drop = True)

# Correction afin que ces variables soient représentées pareil    
df['formePrix'] = np.where(df['formePrix'] == 'Ferme, actualisable', 'Ferme et actualisable', df['formePrix'])
df['procedure'] = np.where(df['procedure'] == 'Appel d’offres restreint', "Appel d'offres restreint", df['procedure'])

######################################################################
################### Identifier les outliers - travail sur les montants
df["montant"] = pd.to_numeric(df["montant"])
df['montantOriginal'] = df["montant"]
df['montant'] = np.where(df['montant'] <= 200, 0, df['montant']) 
df['montant'] = np.where(df['montant'] >= 9.99e8, 0, df['montant'])

######################################################################
#################### Gestion des id/code manquants
df.id = np.where(df.id.isnull(), '0000000000000000', df.id)
df.codeCPV = np.where(df.codeCPV.isnull(), '00000000', df.codeCPV)

## Gestion du montant en fonction du nombre de titulaires
dfCount = df.groupby(['source', '_type', 'id', 'montant', 'acheteur.id',
                    'dureeMois', 'datePublicationDonnees', 'lieuExecution.code', 'codeCPV']).id.count().to_frame('Count?').reset_index()

df = pd.merge(df, dfCount, on=['source', '_type', 'id', 'montant', 'acheteur.id',
                    'dureeMois', 'datePublicationDonnees', 'lieuExecution.code', 'codeCPV'])

# On applique au df la division
df["montant"] = pd.to_numeric(df["montant"])
df["Count?"] = pd.to_numeric(df["Count?"])
df["montant"] = df["montant"]/df["Count?"]

# Nettoyage colonnes
df = df.drop(columns=['index'])
del dfCount
df['montant'] = np.where(df['montant'] == 0, np.NaN, df['montant'])

# Colonne par marché
df['montantTotalMarché'] = df["montant"] * df["Count?"]

###############################################################################
##################### Nettoyage de ces nouvelles colonnes #####################
df.reset_index(inplace=True, drop=True) 
for i in ["\\t","-"," ",".","?","    "]: # Nettoyage des codes
    df.idTitulaires[(df.typeIdentifiant=='SIRET')|(df.typeIdentifiant.isnull())|(df.typeIdentifiant=='nan')] =  df.idTitulaires[(df.typeIdentifiant=='SIRET')|(df.typeIdentifiant.isnull())|(df.typeIdentifiant=='nan')].astype(str).str.replace(i, "")

######## Gestion code CPV
df.codeCPV = df.codeCPV.astype(str)
df["CPV_min"] = df.codeCPV.str[:2]

########  Récupération code NIC 
df.idTitulaires = df.idTitulaires.astype(str)
df['nic'] = df.idTitulaires.str[-5:]
for i in range (len(df)):
    if (df.nic[i].isdigit() == False):
        df.nic[i] = np.NaN

################### Régions / Départements ##################
# Création de la colonne pour distinguer les départements
df['codePostal'] = df['lieuExecution.code'].str[:3]
listCorrespondance = {'976': 'YT', '974': 'RE', '972': 'MQ', '971': 'GP', '973': 'GF'}
for word, initial in listCorrespondance.items():
    df['codePostal'] = np.where(df['codePostal'] == word, initial, df['codePostal'])
df['codePostal'] = df['codePostal'].str[:2]
listCorrespondance = {'YT': '976', 'RE': '974', 'MQ': '972', 'GP': '971', 'GF': '973', 'TF': '98', 'NC' : '988','PF' : '987','WF' : '986','MF' : '978','PM' : '975','BL' : '977'}
for word, initial in listCorrespondance.items():
    df['codePostal'] = np.where(df['codePostal'] == word, initial, df['codePostal'])

# Vérification si c'est bien un code postal
listeCP = ['01','02','03','04','05','06','07','08','09','2A','2B','98','976','974','972','971','973','97','988','987','984','978','975','977', '986'] + [str(i) for i in list(np.arange(10,96,1))]
def check_cp(codePostal):
    if codePostal not in listeCP:
        return np.NaN
    return codePostal
df['codePostal'] = df['codePostal'].apply(check_cp)
#Suppression des codes régions (qui sont retenues jusque là comme des codes postaux)
df['codePostal'] = np.where(df['lieuExecution.typeCode'] == 'Code région', np.NaN, df['codePostal'])

###############################################################################
# Création de la colonne pour distinguer les régions
df['codeRegion'] = df['codePostal'].astype(str)
# Définition des codes des régions en fonctions des codes de départements
listCorrespondance = {'84' : ['01', '03', '07', '15', '26', '38', '42', '43', '63', '69', '73', '74'],
    '27' : ['21', '25', '39', '58', '70', '71', '89', '90'], '53' : ['35', '22', '56', '29'],
    '24' : ['18', '28', '36', '37', '41', '45'], '94' : ['2A', '2B', '20'],
    '44' : ['08', '10', '51', '52', '54', '55', '57', '67', '68', '88'], '32' : ['02', '59', '60', '62', '80'],
    '11' : ['75', '77', '78', '91', '92', '93', '94', '95'], '28' : ['14', '27', '50', '61', '76'],
    '75' : ['16', '17', '19', '23', '24', '33', '40', '47', '64', '79', '86', '87'],
    '76' : ['09', '11', '12', '30', '31', '32', '34', '46', '48', '65', '66', '81', '82'],
    '52' : ['44', '49', '53', '72', '85'], '93' : ['04', '05', '06', '13', '83', '84'],
    '06': ['976'], '04': ['974'], '02': ['972'], '01': ['971'], '03': ['973'], '98': ['97','98','988','986','984','987','975','977','978']}
#Inversion du dict
listCorrespondanceI = {}
for key, value in listCorrespondance.items():
    for string in value:
        listCorrespondanceI.setdefault(string, []).append(key)
listCorrespondanceI={k: str(v[0]) for k,v in listCorrespondanceI.items()}
df['codeRegion']=df['codeRegion'].map(listCorrespondanceI)

# Ajout des codes régions qui existaient déjà dans la colonne lieuExecution.code
df['codeRegion'] = np.where(df['lieuExecution.typeCode'] == "Code région", df['lieuExecution.code'], df['codeRegion'])
df['codeRegion'] = df['codeRegion'].astype(str)
# Vérification des codes région 
listeReg = ['84', '27', '53', '24', '94', '44', '32', '11', '28', '75', '76', '52', '93', '01', '02', '03', '04', '06', '98'] #98 = collectivité d'outre mer
def check_reg(codeRegion):
    if codeRegion not in listeReg:
        return np.NaN
    return codeRegion
df['codeRegion'] = df['codeRegion'].apply(check_reg)

# Identification du nom des régions
df['Region'] = df['codeRegion'].astype(str)
listCorrespondance = {'84' : 'Auvergne-Rhône-Alpes','27' : 'Bourgogne-Franche-Comté','53' : 'Bretagne','24' : 'Centre-Val de Loire',
                      '94' : 'Corse','44' : 'Grand Est','32' : 'Hauts-de-France','11' : 'Île-de-France',
                      '28' : 'Normandie','75' : 'Nouvelle-Aquitaine','76' : 'Occitanie','52' : 'Pays de la Loire',
                      '93' : 'Provence-Alpes-Côte d\'Azur','01' : 'Guadeloupe', '02' : 'Martinique',
                      '03' : 'Guyane','04' : 'La Réunion','06' : 'Mayotte','98' : 'Collectivité d\'outre mer'}
for word, initial in listCorrespondance.items():
    df['Region'] = np.where(df['Region'] == word, initial, df['Region'])

###############################################################################
###############################################################################
del chemin, data, dfO, i, initial, key, listCorrespondance, listCorrespondanceI, string, value, word
#del listeCP, listeReg
###############################################################################
###############################################################################
###############################################################################
################### Date / Temps ##################    
#..............Travail sur les variables de type date           
df.datePublicationDonnees = df.datePublicationDonnees.str[0:10]
df.dateNotification = df.dateNotification.str[0:10] 
#On récupère l'année de notification
df['anneeNotification'] = df.dateNotification.str[0:4] 
df['anneeNotification'] = df['anneeNotification'].astype(float)
#On supprime les erreurs (0021 ou 2100 par exemple)
df['dateNotification'] = np.where(df['anneeNotification'] < 2000, np.NaN, df['dateNotification'])
df['dateNotification'] = np.where(df['anneeNotification'] > 2050, np.NaN, df['dateNotification'])
df['anneeNotification'] = np.where(df['anneeNotification'] < 2000, np.NaN, df['anneeNotification'])
df['anneeNotification'] = np.where(df['anneeNotification'] > 2050, np.NaN, df['anneeNotification'])
df['anneeNotification'] = df.anneeNotification.astype(str).str[:4]

#On récupère le mois de notification
df['moisNotification'] = df.dateNotification.str[5:7] 

######################################################################
# Mise en forme de la colonne montant
df["montant"] = pd.to_numeric(df["montant"])
df["montantOriginal"] = pd.to_numeric(df["montantOriginal"])

df['codePostal'] = df['codePostal'].astype(str)
df['codeRegion'] = df['codeRegion'].astype(str)
df['nic'] = df['nic'].astype(str)

# Mise en forme des données vides
df.datePublicationDonnees = np.where(df.datePublicationDonnees == '', np.NaN, df.datePublicationDonnees)
df.idTitulaires = np.where(df.idTitulaires == '', np.NaN, df.idTitulaires)
df.denominationSociale = np.where((df.denominationSociale == 'N/A') | (df.denominationSociale == 'null'), np.NaN, df.denominationSociale)

######################################################################
# Colonne supplémentaire pour indiquer si la valeur est estimée ou non
df['montantEstime'] = np.where(df['montant'].isnull(), 'Oui', 'Non')

# Utilisation de la méthode 5 pour estimer les valeurs manquantes
df['Region'] = df['Region'].astype(str)
df['formePrix'] = df['formePrix'].astype(str)
df['codeCPV'] = df['codeCPV'].astype(str)

df['moisNotification'] = df['moisNotification'].astype(str)
df['anneeNotification'] = df['anneeNotification'].astype(str)
df['conca'] = df['formePrix'] + df['Region'] + df['codeCPV']
    
df.reset_index(level=0, inplace=True)
df.reset_index(level=0, inplace=True)
del df['index']
# Calcul de la médiane par stratification
medianeRegFP = pd.DataFrame(df.groupby('conca')['montant'].median())
medianeRegFP.reset_index(level=0, inplace=True)
medianeRegFP.columns = ['conca','montantEstimation']
df = pd.merge(df, medianeRegFP, on='conca')
# Remplacement des valeurs manquantes par la médiane du groupe
df['montant'] = np.where(df['montant'].isnull(), df['montantEstimation'], df['montant'])
del df['conca'], df['montantEstimation'], df['level_0']

# On recommence avec une plus petite stratification
df['conca'] = df['formePrix'] + df['Region']
df.reset_index(level=0, inplace=True)
# Calcul de la médiane par stratification
medianeRegFP = pd.DataFrame(df.groupby('conca')['montant'].median())
medianeRegFP.reset_index(level=0, inplace=True)
medianeRegFP.columns = ['conca','montantEstimation']
df = pd.merge(df, medianeRegFP, on='conca')
# Remplacement des valeurs manquantes par la médiane du groupe
df['montant'] = np.where(df['montant'].isnull(), df['montantEstimation'], df['montant'])
# S'il reste encore des valeurs nulles...
df['montant'] = np.where(df['montant'].isnull(), df['montant'].median(), df['montant'])
del df['conca'], df['montantEstimation'], df['index']
del medianeRegFP

##############################################################################
##############################################################################
### Application sur le jeu de données principal df
df['dureeMoisEstime'] = np.where((df['montant']==df['dureeMois'])
    | (df['montant']/df['dureeMois'] < 100)
    | (df['montant']/df['dureeMois'] < 1000) & (df['dureeMois']>=12)
    | ((df['dureeMois'] == 30) & (df['montant'] < 200000))
    | ((df['dureeMois'] == 31) & (df['montant'] < 200000))
    | ((df['dureeMois'] == 360) & (df['montant'] < 10000000))
    | ((df['dureeMois'] == 365) & (df['montant'] < 10000000))
    | ((df['dureeMois'] == 366) & (df['montant'] < 10000000))
    | ((df['dureeMois'] > 120) & (df['montant'] < 2000000)), "Oui", "Non")

df['dureeMoisCalculee'] = np.where(df['dureeMoisEstime'] == "Oui", round(df['dureeMois']/30,0), df['dureeMois'])
df['dureeMoisCalculee'] = np.where(df['dureeMoisCalculee'] == 0, 1, df['dureeMoisCalculee'])

# Au cas ils restent encore des données aberrantes
df['dureeMoisCalculee'] = np.where((df['montant']/df['dureeMois'] < 100)
    | (df['montant']/df['dureeMois'] < 1000) & (df['dureeMois']>=12)
    | ((df['dureeMois'] == 30) & (df['montant'] < 200000))
    | ((df['dureeMois'] == 31) & (df['montant'] < 200000))
    | ((df['dureeMois'] == 360) & (df['montant'] < 10000000))
    | ((df['dureeMois'] == 365) & (df['montant'] < 10000000))
    | ((df['dureeMois'] == 366) & (df['montant'] < 10000000))
    | ((df['dureeMois'] > 120) & (df['montant'] < 2000000)), 1, df.dureeMoisCalculee)

######################################################################
######## Enrichissement des données via les codes siret/siren ########
### Utilisation d'un autre data frame pour traiter les Siret unique
dfSIRET = df[['idTitulaires', 'typeIdentifiant', 'denominationSociale']]
dfSIRET = dfSIRET.drop_duplicates(subset=['idTitulaires'], keep='first')
dfSIRET.reset_index(inplace=True) 
dfSIRET.idTitulaires = dfSIRET.idTitulaires.astype(str)
for i in range (len(dfSIRET)):
    if (dfSIRET.idTitulaires[i].isdigit() == True):
        dfSIRET.typeIdentifiant[i] = 'Oui'
    else:
        dfSIRET.typeIdentifiant[i] = 'Non'
#dfSIRET.idTitulaires = np.where(dfSIRET.typeIdentifiant=='Non', '00000000000000', dfSIRET.idTitulaires)
dfSIRET = dfSIRET[dfSIRET.typeIdentifiant=='Oui']
del dfSIRET['index']
dfSIRET.columns = ['siret', 'siren', 'denominationSociale'] 
dfSIRET.siren = dfSIRET.siret.str[0:9]

#StockEtablissement_utf8
chemin = 'dataEnrichissement/StockEtablissement_utf8.csv'
result = pd.DataFrame(columns = ['siren', 'nic', 'siret', 'typeVoieEtablissement', 'libelleVoieEtablissement', 'codePostalEtablissement', 'libelleCommuneEtablissement', 'codeCommuneEtablissement', 'activitePrincipaleEtablissement', 'nomenclatureActivitePrincipaleEtablissement'])    
dfSIRET['siret'] = dfSIRET['siret'].astype(str)
for gm_chunk in pd.read_csv(chemin, chunksize=1000000, sep=',', encoding='utf-8', usecols=['siren', 'nic',
                                                               'siret', 'typeVoieEtablissement', 
                                                               'libelleVoieEtablissement',
                                                               'codePostalEtablissement',
                                                               'libelleCommuneEtablissement',
                                                               'codeCommuneEtablissement',
                                                               'activitePrincipaleEtablissement',
                                                               'nomenclatureActivitePrincipaleEtablissement']):
    gm_chunk['siret'] = gm_chunk['siret'].astype(str)
    resultTemp = pd.merge(dfSIRET, gm_chunk, on=['siret'])
    result = pd.concat([result, resultTemp], axis=0)
result = result.drop_duplicates(subset=['siret'], keep='first')
del [resultTemp, gm_chunk, chemin]

del result['siren_x'], result['siren_y'], result['siren']
dfSIRET = pd.merge(dfSIRET, result, how='outer', on=['siret'])
nanSiret = dfSIRET[dfSIRET.activitePrincipaleEtablissement.isnull()]
dfSIRET = dfSIRET[dfSIRET.activitePrincipaleEtablissement.notnull()]
nanSiret = nanSiret.iloc[:,:3]

chemin = 'dataEnrichissement/StockEtablissement_utf8.csv'
result2 = pd.DataFrame(columns = ['siren', 'nic', 'siret', 'typeVoieEtablissement', 'libelleVoieEtablissement', 'codePostalEtablissement', 'libelleCommuneEtablissement', 'codeCommuneEtablissement', 'activitePrincipaleEtablissement', 'nomenclatureActivitePrincipaleEtablissement'])    
for gm_chunk in pd.read_csv(chemin, chunksize=1000000, sep=',', encoding='utf-8', usecols=['siren', 'nic',
                                                               'siret', 'typeVoieEtablissement', 
                                                               'libelleVoieEtablissement',
                                                               'codePostalEtablissement',
                                                               'libelleCommuneEtablissement',
                                                               'codeCommuneEtablissement',
                                                               'activitePrincipaleEtablissement',
                                                               'nomenclatureActivitePrincipaleEtablissement']):
    gm_chunk['siren'] = gm_chunk['siren'].astype(str)
    resultTemp = pd.merge(nanSiret, gm_chunk, on=['siren'])
    result2 = pd.concat([result2, resultTemp], axis=0)
result2 = result2.drop_duplicates(subset=['siren'], keep='first')
del result2['siret_x'], result2['siret_y'], result2['siret'], result2['denominationSociale_x']
del [resultTemp, gm_chunk, chemin]

result2 = pd.merge(nanSiret, result2, how='inner', on='siren')
myList = list(result2.columns); myList[2] = 'denominationSociale'; result2.columns = myList
del dfSIRET['denominationSociale_y']
dfSIRET.columns = myList

######## Merge des deux resultats
enrichissementInsee = pd.concat([dfSIRET, result2])

####### Récupération des données tjrs pas enrichies
nanSiren = pd.merge(nanSiret, result2, indicator=True, how='outer', on='siren')
nanSiren = nanSiren[nanSiren['activitePrincipaleEtablissement'].isnull()]
nanSiren = nanSiren.iloc[:,:3]
nanSiren.columns = ['siret', 'siren', 'denominationSociale'] 
nanSiren.reset_index(inplace=True, drop=True)
del dfSIRET, i, nanSiret, result, result2, myList

######################################################################
#....... Solution complémentaire pour ceux non-identifié dans la BDD
df_scrap = pd.DataFrame(columns = ['index', 'rue', 'siret', 'ville', 'typeEntreprise', 'codeType', 'detailsType', 'verification'])    
for i in range(len(nanSiren)):
    try:
        url = 'https://www.infogreffe.fr/entreprise-societe/' + nanSiren.siret[i]
        
        page = requests.get(url)
        tree = html.fromstring(page.content)
        
        rueSiret = tree.xpath('//div[@class="identTitreValeur"]/text()')
        infos = tree.xpath('//p/text()')
        details = tree.xpath('//a/text()')
        
        print(i)
        index = i
        rue = rueSiret[1]
        siret = rueSiret[5].replace(" ","")
        ville = infos[7]
        typeEntreprise = infos[15]
        codeType = infos[16].replace(" : ","")
        detailsType1 = details[28]
        detailsType2 = details[29]
        verification = (siret == nanSiren.siret[i])
        if (detailsType1 ==' '):
            detailType = detailsType2
        else:
            detailsType = detailsType1
        
        if (verification == False):
            codeSiret = tree.xpath('//span[@class="data ficheEtablissementIdentifiantSiret"]/text()')
            infos = tree.xpath('//span[@class="data"]/text()')
            
            index = i
            rue = infos[8]
            siret = codeSiret[0].replace(" ", "")
            ville = infos[9].replace(",\xa0","")
            typeEntreprise = infos[4]
            #codeType = infos[12].replace(" : ","")
            detailsType = infos[11]
            #detailsType2 = infos[29]
            verification = (siret == nanSiren.siret[i])
            
        scrap = pd.DataFrame([index, rue, siret, ville, typeEntreprise, codeType, detailsType, verification]).T; scrap.columns = ['index', 'rue', 'siret', 'ville', 'typeEntreprise', 'codeType', 'detailsType', 'verification']
        df_scrap = pd.concat([df_scrap, scrap], axis=0)
        
    except:
        try :
            url = 'https://www.infogreffe.fr/entreprise-societe/' + nanSiren.siren[i]
        
            page = requests.get(url)
            tree = html.fromstring(page.content)
            
            rueSiret = tree.xpath('//div[@class="identTitreValeur"]/text()')
            infos = tree.xpath('//p/text()')
            details = tree.xpath('//a/text()')
            
            print(i)
            index = i
            rue = rueSiret[1]
            siret = rueSiret[5].replace(" ","")
            ville = infos[7]
            typeEntreprise = infos[15]
            codeType = infos[16].replace(" : ","")
            detailsType1 = details[28]
            detailsType2 = details[29]
            verification = (siret == nanSiren.siret[i])
            if (detailsType1 ==' '):
                detailType = detailsType2
            else:
                detailsType = detailsType1
                
            if (verification == False):
                codeSiret = tree.xpath('//span[@class="data ficheEtablissementIdentifiantSiret"]/text()')
                infos = tree.xpath('//span[@class="data"]/text()')
                
                index = i
                rue = infos[8]
                siret = codeSiret[0].replace(" ", "")
                ville = infos[9].replace(",\xa0","")
                typeEntreprise = infos[4]
                #codeType = infos[12].replace(" : ","")
                detailsType = infos[11]
                #detailsType2 = infos[29]
                verification = (siret == nanSiren.siret[i])
                
                scrap = pd.DataFrame([index, rue, siret, ville, typeEntreprise, codeType, detailsType, verification]).T; scrap.columns = ['index', 'rue', 'siret', 'ville', 'typeEntreprise', 'codeType', 'detailsType', 'verification']
                df_scrap = pd.concat([df_scrap, scrap], axis=0)
        
        except:
            index = i
            scrap = pd.DataFrame([index, ' ', ' ', ' ', ' ', ' ', ' ', False]).T; scrap.columns = ['index', 'rue', 'siret', 'ville', 'typeEntreprise', 'codeType', 'detailsType', 'verification']
            df_scrap = pd.concat([df_scrap, scrap], axis=0)
            pass

# Récupération des résultats
nanSiren.reset_index(inplace=True)
resultat = pd.merge(nanSiren, df_scrap, on='index')
resultatScrap1 = resultat[resultat.rue != ' ']

# Données encore manquantes
dfDS = resultat[resultat.rue == ' ']
dfDS = dfDS.iloc[:,1:4]
dfDS.columns = ['siret', 'siren', 'denominationSociale'] 
dfDS.reset_index(inplace=True, drop=True)
del codeSiret, codeType, detailType, details, detailsType, detailsType1, detailsType2, i, index, infos, rue, rueSiret, scrap, siret, typeEntreprise, url, verification, ville, df_scrap, nanSiren, resultat

######################################################################
def requete(nom):
    pager.get('https://www.infogreffe.fr/recherche-siret-entreprise/chercher-siret-entreprise.html')
    pager.find_element_by_xpath('//*[@id="p1_deno"]').send_keys(nom, Keys.ENTER)
    time.sleep(2)
    url = pager.current_url
    return url
options = Options()
options.add_argument('--headless')
pager = webdriver.Firefox(executable_path = "webdriver/geckodriver.exe", options=options)
#pager = webdriver.PhantomJS('webdriver/phantomjs.exe')

df_scrap2 = pd.DataFrame(columns = ['index', 'rue', 'siret', 'ville', 'typeEntreprise', 'codeType', 'detailsType', 'verification'])    
for i in range(len(dfDS)):
    try:
        url = requete(dfDS.denominationSociale[i])
        
        page = requests.get(url)
        tree = html.fromstring(page.content)
        
        rueSiret = tree.xpath('//div[@class="identTitreValeur"]/text()')
        infos = tree.xpath('//p/text()')
        details = tree.xpath('//a/text()')
        
        print(i)
        index = i
        rue = rueSiret[1]
        siret = rueSiret[5].replace(" ","")
        ville = infos[7]
        typeEntreprise = infos[15]
        codeType = infos[16].replace(" : ","")
        detailsType1 = details[28]
        detailsType2 = details[29]
        verification = (siret == dfDS.siret[i])
        if (detailsType1 ==' '):
            detailType = detailsType2
        else:
            detailsType = detailsType1
        
        scrap2 = pd.DataFrame([index, rue, siret, ville, typeEntreprise, codeType, detailsType, verification]).T; scrap2.columns = ['index', 'rue', 'siret', 'ville', 'typeEntreprise', 'codeType', 'detailsType', 'verification']
        df_scrap2 = pd.concat([df_scrap2, scrap2], axis=0)
    except:
        index = i
        scrap2 = pd.DataFrame([index, ' ', ' ', ' ', ' ', ' ', ' ', False]).T; scrap2.columns = ['index', 'rue', 'siret', 'ville', 'typeEntreprise', 'codeType', 'detailsType', 'verification']
        df_scrap2 = pd.concat([df_scrap2, scrap2], axis=0)
        pass
pager.quit()

# Récupération des résultats
dfDS.reset_index(inplace=True)
resultat = pd.merge(dfDS, df_scrap2, on='index')
resultatScrap2 = resultat[resultat.rue != ' ']

###############################################################################
###############################################################################
###############################################################################
dfDS.to_csv(r'dfDS.csv', sep=';',index = False, header=True, encoding='utf-8')
resultat.to_csv(r'resultat.csv', sep=';',index = False, header=True, encoding='utf-8')
resultatScrap2.to_csv(r'resultatScrap2.csv', sep=';',index = False, header=True, encoding='utf-8')

errorSIRET = resultat[(resultat.siret_y=='')|(resultat.siret_y=='')|(resultat.siret_y==' ')|(resultat.siret_y.isnull())]
errorSIRET = errorSIRET[['siret_x', 'siren', 'denominationSociale']]; errorSIRET.columns = ['siret', 'siren', 'denominationSociale']; errorSIRET.reset_index(inplace=True, drop=True)
errorSIRET.to_csv(r'errorSIRET.csv', sep=';',index = False, header=True, encoding='utf-8')
###############################################################################
###############################################################################
###############################################################################

# On réuni les résultats du scraping
enrichissementScrap = pd.concat([resultatScrap1, resultatScrap2])
del enrichissementScrap['index'], enrichissementScrap['siret_y'], enrichissementScrap['verification']

############ Arrangement des colonnes 
# Gestion bdd insee
enrichissementInsee.reset_index(inplace=True, drop=True)
enrichissementInsee['typeVoieEtablissement'].unique()
listCorrespondance = {'ALL': 'Allée', 'AV': 'Avenue', 'BD': 'Boulevard', 'CAR': 'Carrefour',
                      'CHE': 'Chemin', 'CHS': 'Chaussée', 'CITE': 'Cité', 'COR': 'Corniche',
                      'CRS': 'Cours', 'DOM': 'Domaine', 'DSC': 'Descente', 'ECA': 'Ecart',
                      'ESP': 'Esplanade', 'FG': 'Faubourg', 'GR': 'Grande Rue', 'HAM': 'Hameau',
                      'HLE': 'Halle', 'IMP': 'Impasse', 'LD': 'Lieu dit', 'LOT': 'Lotissement',
                      'MAR': 'Marché', 'MTE': 'Montée', 'PAS': 'Passage', 'PL': 'Place', 
                      'PLN': 'Plaine', 'PLT': 'Plateau', 'PRO': 'Promenade', 'PRV': 'Parvis',
                      'QUA': 'Quartier', 'QUAI': 'Quai', 'RES': 'Résidence', 'RLE': 'Ruelle',
                      'ROC': 'Rocade', 'RPT': 'Rond Point', 'RTE': 'Route', 'RUE': 'Rue', 
                      'SEN': 'Sentier', 'SQ': 'Square', 'TPL': 'Terre-plein', 'TRA': 'Traverse',
                      'VLA': 'Villa', 'VLGE': 'Village'}
for word, initial in listCorrespondance.items():
    enrichissementInsee['typeVoieEtablissement'] = enrichissementInsee['typeVoieEtablissement'].replace(word, initial)
enrichissementInsee['rue'] = enrichissementInsee.typeVoieEtablissement + ' ' + enrichissementInsee.libelleVoieEtablissement
enrichissementInsee['activitePrincipaleEtablissement'] = enrichissementInsee['activitePrincipaleEtablissement'].str.replace(".", "")
del enrichissementInsee['typeVoieEtablissement'], enrichissementInsee['libelleVoieEtablissement'], enrichissementInsee['nic'], enrichissementInsee['nomenclatureActivitePrincipaleEtablissement']

# Gestion bdd scrap
enrichissementScrap.reset_index(inplace=True, drop=True)
enrichissementScrap["codePostal"] = np.nan
enrichissementScrap["commune"] = np.nan
enrichissementScrap.codePostal = enrichissementScrap.codePostal.astype(str)
enrichissementScrap.commune = enrichissementScrap.ville.astype(str)
enrichissementScrap.rue = enrichissementScrap.rue.astype(str)

enrichissementScrap["codePostal"] = enrichissementScrap.ville.str[0:7]
enrichissementScrap["codePostal"] = enrichissementScrap["codePostal"].str.replace(" ", "")
enrichissementScrap["commune"] = enrichissementScrap.ville.str[7:]
del enrichissementScrap['ville'], enrichissementScrap['typeEntreprise'], enrichissementScrap['detailsType']

# Renomme les colonnes
enrichissementScrap.columns = ['siret', 'siren', 'denominationSociale', 'adresseEtablissement', 'codeTypeEtablissement', 'codePostalEtablissement', 'communeEtablissement']
enrichissementInsee.columns = ['siret', 'siren', 'denominationSociale', 'codeTypeEtablissement', 'codeCommuneEtablissement', 'codePostalEtablissement', 'communeEtablissement', 'adresseEtablissement']

# df final pour enrichir les données des entreprises
dfenrichissement = pd.concat([enrichissementInsee, enrichissementScrap])
dfenrichissement = dfenrichissement.astype(str)
# On s'assure qu'il n'y ai pas de doublons
dfenrichissement = dfenrichissement.drop_duplicates(subset=['siret'], keep=False)

########### Ajout au df principal !
del df['denominationSociale']
# Concaténation
df =  pd.merge(df, dfenrichissement, how='outer', left_on="idTitulaires", right_on="siret")
del df['CPV_min'], df['uid'], df['uuid']

######################################################################
################### Enrichissement avec le code CPV ##################
######################################################################
# Importation et mise en forme des codes/ref CPV
refCPV = pd.read_excel("dataEnrichissement/cpv_2008_ver_2013.xlsx", usecols=['CODE', 'FR'])
refCPV.columns = ['CODE', 'refCodeCPV']
refCPV_min = pd.DataFrame.copy(refCPV, deep = True)
refCPV_min["CODE"] = refCPV_min.CODE.str[0:8]
refCPV_min = refCPV_min.drop_duplicates(subset=['CODE'], keep='first')
refCPV_min.columns = ['CODEmin', 'FR2']
# Merge avec le df principal
df = pd.merge(df, refCPV, how='left', left_on="codeCPV", right_on="CODE")
df = pd.merge(df, refCPV_min, how='left', left_on="codeCPV", right_on="CODEmin")
# Garde uniquement la colonne utile / qui regroupe les nouvelles infos
df.refCodeCPV = np.where(df.refCodeCPV.isnull(), df.FR2, df.refCodeCPV)
del df['CODE'], df['CODEmin'], df['FR2'], refCPV, refCPV_min, i

######################################################################
############## Enrichissement des données des acheteurs ##############
######################################################################
######## Enrichissement des données via les codes siret/siren ########
### Utilisation d'un autre data frame pour traiter les Siret unique : acheteur.id
dfAcheteurId = df[['acheteur.id']]; dfAcheteurId.columns = ['siret']
dfAcheteurId = dfAcheteurId.drop_duplicates(subset=['siret'], keep='first')
dfAcheteurId.reset_index(inplace=True, drop=True) 
dfAcheteurId.siret = dfAcheteurId.siret.astype(str)

#StockEtablissement_utf8
chemin = 'dataEnrichissement/StockEtablissement_utf8.csv'
result = pd.DataFrame(columns = ['siret', 'codePostalEtablissement', 'libelleCommuneEtablissement', 'codeCommuneEtablissement'])    
for gm_chunk in pd.read_csv(chemin, chunksize=1000000, sep=',', encoding='utf-8', usecols=['siret', 'codePostalEtablissement', 
                                                                                           'libelleCommuneEtablissement', 
                                                                                           'codeCommuneEtablissement']):
    gm_chunk['siret'] = gm_chunk['siret'].astype(str)
    resultTemp = pd.merge(dfAcheteurId, gm_chunk, on=['siret'])
    result = pd.concat([result, resultTemp], axis=0)
result = result.drop_duplicates(subset=['siret'], keep='first')

dfAcheteurId["siren"] = np.nan
dfAcheteurId.siren = dfAcheteurId.siret.str[0:9]
dfAcheteurId.siren = dfAcheteurId.siren.astype(int)
dfAcheteurId.siren = dfAcheteurId.siren.astype(str)
chemin = 'dataEnrichissement/StockEtablissement_utf8.csv'
result2 = pd.DataFrame(columns = ['siren', 'codePostalEtablissement', 'libelleCommuneEtablissement', 'codeCommuneEtablissement'])    
for gm_chunk in pd.read_csv(chemin, chunksize=1000000, sep=',', encoding='utf-8', usecols=['siren', 'codePostalEtablissement', 
                                                                                           'libelleCommuneEtablissement', 
                                                                                           'codeCommuneEtablissement']):
    gm_chunk['siren'] = gm_chunk['siren'].astype(str)
    resultTemp = pd.merge(dfAcheteurId, gm_chunk, on="siren")
    result2 = pd.concat([result2, resultTemp], axis=0)
result2 = result2.drop_duplicates(subset=['siren'], keep='first')
siret = pd.DataFrame(result['siret']); siret.columns=['s']
result2 = pd.merge(result2, siret, how='outer',  left_on='siret', right_on='s')
result2 = result2[result2.s.isnull()]; del result2['s']

dfManquant = pd.merge(dfAcheteurId, result, how='outer', on='siret')
dfManquant = dfManquant[dfManquant['codePostalEtablissement'].isnull()]
dfManquant  = dfManquant .iloc[:,:2]
result2 = pd.merge(dfManquant, result2, how='inner', on='siren')
del result2['siret_y'], result2['siren']
result2.columns = ['siret', 'codeCommuneEtablissement', 'codePostalEtablissement', 'libelleCommuneEtablissement']

enrichissementAcheteur = pd.concat([result, result2])
enrichissementAcheteur.columns = ['codeCommuneAcheteur', 'codePostalAcheteur', 'libelleCommuneAcheteur', 'acheteur.id']

df = pd.merge(df, enrichissementAcheteur, how='outer', on='acheteur.id')
del chemin, dfAcheteurId, dfManquant, enrichissementAcheteur, gm_chunk, result, result2, resultTemp, siret

######################################################################
######################################################################
# Ajustement de certaines colonnes
df.codePostalEtablissement = df.codePostalEtablissement.astype(str).str[:5]
df.anneeNotification = df.anneeNotification.astype(str)
df.codePostal = df.codePostal.astype(str)

# Réorganisation des colonnes et de leur nom
df.columns = ['source', 'type', 'nature', 'procedure', 'dureeMois',
       'datePublicationDonnees', 'lieuExecutionCode',
       'lieuExecutionTypeCode', 'lieuExecutionNom', 'identifiantMarche', 'objetMarche', 'codeCPV',
       'dateNotification', 'montant', 'formePrix', 'acheteurId',
       'acheteurNom', 'typeIdentifiantEtablissement', 'idEtablissement', 'montantOriginal', 'nbTitulairesSurCeMarche',
       'montantTotalMarche', 'nicEtablissement', 'codeDepartementAcheteur', 'codeRegionAcheteur', 'regionAcheteur',
       'anneeNotification', 'moisNotification', 'montantEstEstime',
       'dureeMoisEstEstime', 'dureeMoisCalculee', 'adresseEtablissement',
       'codeCommuneEtablissement', 'codePostalEtablissement',
       'codeTypeEtablissement', 'communeEtablissement', 'denominationSocialeEtablissement',
       'sirenEtablissement', 'siretEtablissement', 'referenceCPV', 'codeCommuneAcheteur',
       'codePostalAcheteur', 'libelleCommuneAcheteur'] 

df = df[['source', 'type', 'nature', 'procedure', 'datePublicationDonnees', 'dateNotification',  
         'anneeNotification', 'moisNotification', 'formePrix', 'identifiantMarche', 'objetMarche' , 'codeCPV',
         'referenceCPV', 'montantOriginal', 'montant', 'montantEstEstime', 'montantTotalMarche', 'nbTitulairesSurCeMarche',
         'dureeMois', 'dureeMoisEstEstime', 'dureeMoisCalculee', 'acheteurId', 'acheteurNom',
         'lieuExecutionCode', 'lieuExecutionTypeCode', 'lieuExecutionNom', 'codeCommuneAcheteur',
         'codePostalAcheteur', 'libelleCommuneAcheteur', 'codeDepartementAcheteur', 'codeRegionAcheteur', 'regionAcheteur',
         'typeIdentifiantEtablissement', 'idEtablissement', 'nicEtablissement', 'adresseEtablissement',
         'codeCommuneEtablissement', 'codePostalEtablissement', 'codeTypeEtablissement', 'communeEtablissement',
         'denominationSocialeEtablissement','sirenEtablissement', 'siretEtablissement']]

# Rectification codePostalAcheteur et codeCommuneEtablissement
df.codePostalAcheteur = df.codePostalAcheteur.astype(str).str[:5]
df.codeCommuneEtablissement = df.codeCommuneEtablissement.astype(str).str[:5]
######################################################################
df_decp = pd.DataFrame.copy(df, deep = True); del df
######################################################################
######## Enrichissement latitude & longitude avec adresse la ville 
df_villes = pd.read_csv('dataEnrichissement/code-insee-postaux-geoflar.csv', 
                        sep=';', header = 0, error_bad_lines=False,
                        usecols=['CODE INSEE', 'geom_x_y', 'Superficie', 'Population'])
df_villes['ordre']=0
df_villes2 = pd.read_csv('dataEnrichissement/code-insee-postaux-geoflar.csv', 
                        sep=';', header = 0, error_bad_lines=False,
                        usecols=['Code commune complet', 'geom_x_y', 'Superficie', 'Population'])
df_villes2['ordre']=1
df_villes2.columns = ['geom_x_y', 'Superficie', 'Population', 'CODE INSEE', 'ordre']
df_villes = pd.concat([df_villes2, df_villes])
del df_villes2
#Suppression des doublons
df_villes = df_villes.sort_values(by = 'ordre', ascending = False)
df_villes.reset_index(inplace=True, drop=True)
df_villes = df_villes.drop_duplicates(subset=['CODE INSEE', 'geom_x_y', 'Superficie', 'Population'], keep='last')
df_villes = df_villes.drop_duplicates(subset=['CODE INSEE'], keep='last')
df_villes = df_villes[(df_villes['CODE INSEE'].notnull()) & (df_villes.geom_x_y.notnull())]
del df_villes['ordre']
df_villes.reset_index(inplace=True, drop=True)
#Multiplier population par 1000
df_villes.Population = df_villes.Population.astype(float)
df_villes.Population = round(df_villes.Population*1000,0)
# Divise la colonne geom_x_y pour obtenir la latitude et la longitude séparemment
# Latitude avant longitude
df_villes.geom_x_y = df_villes.geom_x_y.astype(str)
df_sep = pd.DataFrame(df_villes.geom_x_y.str.split(',',1, expand=True))
df_sep.columns = ['latitude','longitude']

df_villes = df_villes.join(df_sep)
del df_villes['geom_x_y'], df_sep
df_villes.latitude = df_villes.latitude.astype(float)
df_villes.longitude = df_villes.longitude.astype(float)

################################# Ajout au dataframe principal
# Ajout pour les acheteurs
df_villes.columns = ['codeCommuneAcheteur', 'populationAcheteur', 'superficieAcheteur', 'latitudeAcheteur','longitudeAcheteur']
df_decp = pd.merge(df_decp, df_villes, how='left', on='codeCommuneAcheteur')
# Ajout pour les etablissement
df_villes.columns = ['codeCommuneEtablissement', 'populationEtablissement', 'superficieEtablissement', 'latitudeEtablissement','longitudeEtablissement']
df_decp = pd.merge(df_decp, df_villes, how='left', on='codeCommuneEtablissement')
del df_villes
########### Calcul de la distance entre l'acheteur et l'etablissement
# Utilisation de la formule de Vincenty avec le rayon moyen de la Terre
#df_decp['distanceAcheteurEtablissement'] = round((((2*6378137+6356752)/3)*np.arctan2(np.sqrt((np.cos(np.radians(df_decp.latitudeEtablissement))*np.sin(np.radians(np.fabs(df_decp.longitudeEtablissement-df_decp.longitudeAcheteur))))*(np.cos(np.radians(df_decp.latitudeEtablissement))*np.sin(np.radians(np.fabs(df_decp.longitudeEtablissement-df_decp.longitudeAcheteur)))) + (np.cos(np.radians(df_decp.latitudeAcheteur))*np.sin(np.radians(df_decp.latitudeEtablissement)) - np.sin(np.radians(df_decp.latitudeAcheteur))*np.cos(np.radians(df_decp.latitudeEtablissement))*np.cos(np.radians(np.fabs(df_decp.longitudeEtablissement-df_decp.longitudeAcheteur))))*(np.cos(np.radians(df_decp.latitudeAcheteur))*np.sin(np.radians(df_decp.latitudeEtablissement)) - np.sin(np.radians(df_decp.latitudeAcheteur))*np.cos(np.radians(df_decp.latitudeEtablissement))*np.cos(np.radians(np.fabs(df_decp.longitudeEtablissement-df_decp.longitudeAcheteur))))), (np.sin(np.radians(df_decp.latitudeAcheteur)))*(np.sin(np.radians(df_decp.latitudeEtablissement))) + (np.cos(np.radians(df_decp.latitudeAcheteur)))*(np.cos(np.radians(df_decp.latitudeEtablissement)))*(np.cos(np.radians(np.fabs(df_decp.longitudeEtablissement-df_decp.longitudeAcheteur))))))/1000,0)
df_decp['distanceAcheteurEtablissement'] = round((((2*6378137+6356752)/3)*np.arctan2(
        np.sqrt((np.cos(np.radians(df_decp.latitudeEtablissement))*np.sin(
        np.radians(np.fabs(df_decp.longitudeEtablissement-df_decp.longitudeAcheteur))))*(
        np.cos(np.radians(df_decp.latitudeEtablissement))*np.sin(np.radians(np.fabs(
        df_decp.longitudeEtablissement-df_decp.longitudeAcheteur)))) + (np.cos(np.radians(
        df_decp.latitudeAcheteur))*np.sin(np.radians(df_decp.latitudeEtablissement)) - np.sin(
        np.radians(df_decp.latitudeAcheteur))*np.cos(np.radians(df_decp.latitudeEtablissement))*np.cos(
        np.radians(np.fabs(df_decp.longitudeEtablissement-df_decp.longitudeAcheteur))))*(
        np.cos(np.radians(df_decp.latitudeAcheteur))*np.sin(np.radians(df_decp.latitudeEtablissement)) - np.sin(
        np.radians(df_decp.latitudeAcheteur))*np.cos(np.radians(df_decp.latitudeEtablissement))*np.cos(
        np.radians(np.fabs(df_decp.longitudeEtablissement-df_decp.longitudeAcheteur))))), (np.sin(
        np.radians(df_decp.latitudeAcheteur)))*(np.sin(np.radians(df_decp.latitudeEtablissement))) + (
        np.cos(np.radians(df_decp.latitudeAcheteur)))*(np.cos(np.radians(df_decp.latitudeEtablissement)))*(
        np.cos(np.radians(np.fabs(df_decp.longitudeEtablissement-df_decp.longitudeAcheteur))))))/1000,0)

# Taux d'enrichissement
round(100-df_decp.distanceAcheteurEtablissement.isnull().sum()/len(df_decp)*100,2)

# Remise en forme des colonnes géo-spatiales
df_decp.latitudeAcheteur = df_decp.latitudeAcheteur.astype(str)
df_decp.longitudeAcheteur = df_decp.longitudeAcheteur.astype(str)
df_decp['geomAcheteur'] = df_decp.latitudeAcheteur + ',' + df_decp.longitudeAcheteur
df_decp.latitudeEtablissement = df_decp.latitudeEtablissement.astype(str)
df_decp.longitudeEtablissement = df_decp.longitudeEtablissement.astype(str)
df_decp['geomEtablissement'] = df_decp.latitudeEtablissement + ',' + df_decp.longitudeEtablissement

df_decp['geomAcheteur'] = np.where(df_decp['geomAcheteur'] == 'nan,nan', np.NaN, df_decp['geomAcheteur'])
df_decp['geomEtablissement'] = np.where(df_decp['geomEtablissement'] == 'nan,nan', np.NaN, df_decp['geomEtablissement'])
df_decp.reset_index(inplace=True, drop=True)

###############################################################################
###############################################################################
###############################################################################
############........ CARTE DES MARCHES PAR VILLE
df_carte = df_decp[['latitudeAcheteur', 'longitudeAcheteur', 'libelleCommuneAcheteur']]
df_carte=df_carte[df_carte['latitudeAcheteur'] != 'nan']
df_carte=df_carte[df_carte['longitudeAcheteur'] != 'nan']
df_carte = df_carte.drop_duplicates(subset=['latitudeAcheteur', 'longitudeAcheteur'], keep='first')
df_carte.reset_index(inplace=True, drop=True)

dfMT = df_decp.groupby(['latitudeAcheteur', 'longitudeAcheteur']).montant.sum().to_frame('montantTotal').reset_index()
dfMM = df_decp.groupby(['latitudeAcheteur', 'longitudeAcheteur']).montant.mean().to_frame('montantMoyen').reset_index()
dfIN = df_decp.groupby(['latitudeAcheteur', 'longitudeAcheteur']).identifiantMarche.nunique().to_frame('nbMarches').reset_index()
dfSN = df_decp.groupby(['latitudeAcheteur', 'longitudeAcheteur']).siretEtablissement.nunique().to_frame('nbEntreprises').reset_index()
dfDM = df_decp.groupby(['latitudeAcheteur', 'longitudeAcheteur']).distanceAcheteurEtablissement.median().to_frame('distanceMoyenne').reset_index()

df_carte = pd.merge(df_carte, dfMT, how='left', on=['latitudeAcheteur', 'longitudeAcheteur'])
df_carte = pd.merge(df_carte, dfMM, how='left', on=['latitudeAcheteur', 'longitudeAcheteur'])
df_carte = pd.merge(df_carte, dfIN, how='left', on=['latitudeAcheteur', 'longitudeAcheteur'])
df_carte = pd.merge(df_carte, dfSN, how='left', on=['latitudeAcheteur', 'longitudeAcheteur'])
df_carte = pd.merge(df_carte, dfDM, how='left', on=['latitudeAcheteur', 'longitudeAcheteur'])
del dfMM, dfMT, dfIN, dfSN, dfDM

df_carte.montantTotal = round(df_carte.montantTotal, 0)
df_carte.montantMoyen = round(df_carte.montantMoyen, 0)
df_carte.nbMarches = round(df_carte.nbMarches, 0)
df_carte.nbEntreprises = round(df_carte.nbEntreprises, 0)
df_carte.distanceMoyenne = round(df_carte.distanceMoyenne, 0)
df_carte.distanceMoyenne = np.where(df_carte.distanceMoyenne.isnull(), 0, df_carte.distanceMoyenne)

### Mise en forme
c= folium.Map(location=[47, 2.0],zoom_start=6, tiles='OpenStreetMap')
marker_cluster = MarkerCluster().add_to(c)
for i in range (len(df_carte)):
    folium.Marker([df_carte.latitudeAcheteur[i],  df_carte.longitudeAcheteur[i]], 
                  icon=folium.features.CustomIcon('https://icon-library.com/images/map-pin-icon/map-pin-icon-17.jpg', icon_size=(max(20, min(40,df_carte.distanceMoyenne[i]/2)), max(20, min(40,df_carte.distanceMoyenne[i]/2)))),
                  popup = folium.Popup('<b>' + df_carte.libelleCommuneAcheteur[i] + '</b></br>'
                  + '<b>' + df_carte.nbMarches[i].astype(str) + '</b> marchés '
                  #+ 'Montant total des marchés : ' + df_carte.montantTotal[i].astype(str) + ' €' + '</br>'
                  + 'pour un montant moyen de <b>' + round(df_carte.montantMoyen[i]/1000,0).astype(int).astype(str) + ' mille euros</b> '
                  + "</br>avec <b>" + df_carte.nbEntreprises[i].astype(str) + ' entreprises</b> '
                  + "à une distance médiane de <b>" + df_carte.distanceMoyenne[i].astype(str) + ' km</b> ',
                  max_width = 320, min_width = 200)  
                  , clustered_marker = True).add_to(marker_cluster)
c.save('carte/carteDECP.html')

###############################################################################
###############################################################################
del df_decp['superficieEtablissement'], df_decp['populationEtablissement'], df_decp['latitudeAcheteur'], df_decp['longitudeAcheteur'], df_decp['latitudeEtablissement'], df_decp['longitudeEtablissement']

###############################################################################
############################ Segmentation de marché ###########################
###############################################################################
#... Créer une bdd par villes (acheteur/client)
dfBIN = df_decp[['type', 'nature', 'procedure', 'lieuExecutionTypeCode', 'regionAcheteur']]
# Arrangement du code du lieu d'exécution
dfBIN['lieuExecutionTypeCode'] = dfBIN['lieuExecutionTypeCode'].str.upper()
dfBIN['lieuExecutionTypeCode'] = np.where(dfBIN['lieuExecutionTypeCode'] == 'CODE DÉPARTEMENT', 'CODE DEPARTEMENT', dfBIN['lieuExecutionTypeCode'])
dfBIN['lieuExecutionTypeCode'] = np.where(dfBIN['lieuExecutionTypeCode'] == 'CODE RÉGION', 'CODE REGION', dfBIN['lieuExecutionTypeCode'])
dfBIN['lieuExecutionTypeCode'] = np.where(dfBIN['lieuExecutionTypeCode'] == 'CODE ARRONDISSEMENT', 'CODE DEPARTEMENT', dfBIN['lieuExecutionTypeCode'])
dfBIN['lieuExecutionTypeCode'] = np.where((dfBIN['lieuExecutionTypeCode'] == 'CODE COMMUNE') | (dfBIN['lieuExecutionTypeCode'] == 'CODE POSTAL'), 'CODE COMMUNE/POSTAL', dfBIN['lieuExecutionTypeCode'])

#... On binarise les variables qualitatives
def binateur(data, to_bin):
    data = data.copy()
    X = data[to_bin]
    X = pd.get_dummies(X)
    data = data.drop(columns=to_bin)
    X = X.fillna(0)
    return pd.concat([data, X], axis=1)

dfBIN = binateur(dfBIN, dfBIN.columns) 

#... Selection des variables quantitatives + nom de la commune
dfNoBin = df_decp[['libelleCommuneAcheteur', 'montant', 'dureeMois', 'dureeMoisCalculee', 'distanceAcheteurEtablissement']]
# Création d'une seule colonne pour la durée du marché
dfNoBin['duree'] = round(dfNoBin.dureeMoisCalculee, 0)
del dfNoBin['dureeMois'], dfNoBin['dureeMoisCalculee']
# On modifie les valeurs manquantes pour la distance en appliquant la médiane
dfNoBin.distanceAcheteurEtablissement = np.where(dfNoBin['distanceAcheteurEtablissement'].isnull(), dfNoBin['distanceAcheteurEtablissement'].median(), dfNoBin['distanceAcheteurEtablissement'])

# On obtient alors notre df prêt sans variables qualitatives (sauf libellé)
df = dfNoBin.join(dfBIN)
del dfNoBin, dfBIN
df = df[df['libelleCommuneAcheteur'].notnull()]
df['nbContrats'] = 1 # Trouver autre solution

#... Gestion des régions
df = df.groupby(['libelleCommuneAcheteur']).sum().reset_index()
ensemble = ['regionAcheteur_Auvergne-Rhône-Alpes',
       'regionAcheteur_Bourgogne-Franche-Comté', 'regionAcheteur_Bretagne',
       'regionAcheteur_Centre-Val de Loire',
       "regionAcheteur_Collectivité d'outre mer", 'regionAcheteur_Corse',
       'regionAcheteur_Grand Est', 'regionAcheteur_Guadeloupe',
       'regionAcheteur_Guyane', 'regionAcheteur_Hauts-de-France',
       'regionAcheteur_La Réunion', 'regionAcheteur_Martinique',
       'regionAcheteur_Mayotte', 'regionAcheteur_Normandie',
       'regionAcheteur_Nouvelle-Aquitaine', 'regionAcheteur_Occitanie',
       'regionAcheteur_Pays de la Loire',
       "regionAcheteur_Provence-Alpes-Côte d'Azur",
       'regionAcheteur_Île-de-France']
df['HighScore'] = df[ensemble].max(axis=1)
for x in ensemble:
    df[x] = np.where(df[x] == df['HighScore'], 1, 0)

#... Fréquence 
ensemble = ['nature_Accord-cadre', 'nature_CONCESSION DE SERVICE',
       'nature_CONCESSION DE SERVICE PUBLIC', 'nature_CONCESSION DE TRAVAUX',
       'nature_Concession de service', 'nature_Concession de service public',
       'nature_Concession de travaux', 'nature_DELEGATION DE SERVICE PUBLIC',
       'nature_Délégation de service public', 'nature_Marché',
       'nature_Marché de partenariat', 'nature_Marché hors accord cadre',
       'nature_Marché subséquent', "procedure_Appel d'offres ouvert",
       "procedure_Appel d'offres restreint", 'procedure_Dialogue compétitif',
       'procedure_Marché négocié sans publicité ni mise en concurrence préalable',
       'procedure_Marché public négocié sans publicité ni mise en concurrence préalable',
       'procedure_Procédure adaptée', 'procedure_Procédure avec négociation',
       'procedure_Procédure non négociée ouverte',
       'procedure_Procédure non négociée restreinte',
       'procedure_Procédure négociée ouverte',
       'procedure_Procédure négociée restreinte',
       'lieuExecutionTypeCode_CODE CANTON',
       'lieuExecutionTypeCode_CODE COMMUNE/POSTAL',
       'lieuExecutionTypeCode_CODE DEPARTEMENT',
       'lieuExecutionTypeCode_CODE PAYS', 'lieuExecutionTypeCode_CODE REGION']
for x in ensemble:
    df[x] = df[x]/df['nbContrats']
del df['HighScore'], ensemble, x

#... Duree, montant et distance moyenne par ville (par rapport au nb de contrats)
df.distanceAcheteurEtablissement = round(df.distanceAcheteurEtablissement/df['nbContrats'],0)
df.duree = round(df.duree/df['nbContrats'],0)
df['montantMoyen'] = round(df.montant/df['nbContrats'],0)

#... Finalement les données spatiales ne sont pas gardés pour réaliser la segmentation
df.drop(columns = df.columns[35:55], axis = 1, inplace = True)

# Renomme des colonnes
df=df.rename(columns = {'montant': 'montantTotal', 'distanceAcheteurEtablissement': 'distanceMoyenne', 'duree': 'dureeMoyenne', 
                     'type_Contrat de concession': 'nbContratDeConcession', 'type_Marché': 'nbMarché'})

#... Mettre les valeurs sur une même unité de mesure
df_nom = pd.DataFrame(df.libelleCommuneAcheteur)
del df['libelleCommuneAcheteur']
scaler = StandardScaler()
scaled_df = scaler.fit_transform(df)

#... On réassemble le df
df = df_nom.join(df)
del df_nom

###############################################################################
### Réalisation de l'ACP
n=np.shape(scaled_df)[0] #nb lignes
p=np.shape(scaled_df)[1] #nb col
acp = PCA(svd_solver='full')
coord = acp.fit_transform(scaled_df)
#scree plot
eigval = (n-1)/n*acp.explained_variance_
plt.plot(np.arange(1,p+1), eigval)
#cumul de variance expliquée
plt.plot(np.arange(1,p+1),np.cumsum(acp.explained_variance_ratio_))
# Test des bâtons brisés
bs = np.cumsum(1/np.arange(p,0,-1))[::-1]
# D'après les résultats aucun facteur n'est valide...
print(pd.DataFrame({'Val.Propre':eigval,'Seuils':bs}))

###############################################################################
### Application de l'algorithme des k-means - on prend 7 grappes
model=KMeans(n_clusters=7)
model.fit(scaled_df)
print(model.cluster_centers_)
print(model.labels_)
res = model.labels_
    
# Graphique du résultat
for point in scaled_df:
    clusterID = model.predict(point.reshape(1,-1))
    if clusterID == [0]:
        plt.scatter(point[0], point[1], c='b')
    elif clusterID == [1]:
        plt.scatter(point[0], point[1], c='g')
    elif clusterID == [2]:
        plt.scatter(point[0], point[1], c='r')
    elif clusterID == [3]:
        plt.scatter(point[0], point[1], c='c')
    elif clusterID == [4]:
        plt.scatter(point[0], point[1], c='m')
    elif clusterID == [5]:
        plt.scatter(point[0], point[1], c='y')
    elif clusterID == [6]:
        plt.scatter(point[0], point[1], c='k')
#for center in model.cluster_centers_:
#    plt.scatter(center[0],center[1])
plt.show()

# Nombre de communes par grappe
for i in range(7):
    print((model.labels_==i).sum())

# Ajout des résultats
res = pd.DataFrame(res, columns=['segmentation_KMEANS'])
df = df.join(res)
del coord, eigval, i, point, res, bs, clusterID #center

###############################################################################
### Application de l'algorithme de classification ascendante hiérarchique - CAH
############ Avec les données normalisée
# Générer la matrice des liens
Z = linkage(scaled_df ,method='ward',metric='euclidean')
# Dendrogramme
plt.title('CAH avec matérialisation des X classes')
dendrogram(Z,labels=df.index,orientation='left',color_threshold=65)
plt.show()
# Récupération des classes
groupes_cah = pd.DataFrame(fcluster(Z,t=65,criterion='distance'), columns = ['segmentation_CAH'])
### Ajout au df 
df = df.join(groupes_cah)
del Z, groupes_cah, scaled_df

###############################################################################
### Comparons les résultats des deux méthodes
pd.crosstab(df.segmentation_CAH, df.segmentation_KMEANS)
resTest = df[(df['segmentation_CAH']==1) | (df['segmentation_CAH']==6) | (df['segmentation_CAH']==5)].groupby(['segmentation_CAH']).mean()
resTest2 = df[(df['segmentation_KMEANS']==0) | (df['segmentation_KMEANS']==1) | (df['segmentation_KMEANS']==4)].groupby(['segmentation_KMEANS']).mean()
del resTest, resTest2

# Conclusion
# Séelctionner le clustering avec le CAH car :
    # Résultat reproductible (pas d'aléatiore)
    # Forme des amas non hyper-sphérique
    # Gère mieux les outliers / plus précis
    # On ne connait pas à l'avance le nombre k de cluster
###############################################################################
### Ratio nb entreprises / nb marchés
df_carte['ratioEntreprisesMarchés']=df_carte['nbEntreprises']/df_carte['nbMarches']
df_bar = df_carte[['libelleCommuneAcheteur', 'nbMarches', 'ratioEntreprisesMarchés']]
df_bar = df_bar[(df_bar.nbMarches>100) & (df_bar.ratioEntreprisesMarchés>0)]
df_bar = df_bar.sort_values(by = 'ratioEntreprisesMarchés').sort_values(by = 'ratioEntreprisesMarchés', ascending = True)
# Graphique des résultats : top 10
df_barGraph = df_bar.head(10)
df_barGraph.ratioEntreprisesMarchés.plot(kind='barh', title='Top 10 des communes avec le plus petit ratio NBentreprise/NBmarchés')
plt.yticks(range(0,len(df_barGraph.libelleCommuneAcheteur)), df_barGraph.libelleCommuneAcheteur)
del df_barGraph
round(df_bar.ratioEntreprisesMarchés.mean(),2)
df_bar.to_csv(r'resultatsCSV/df_Ratio.csv', sep=';',index = False, header=True, encoding='utf-8')

### HeatMap montantTotal / Population
df_HeatMap = pd.merge(df_carte, df_decp[['populationAcheteur','libelleCommuneAcheteur']], how='inner', on=['libelleCommuneAcheteur'])
df_HeatMap = df_HeatMap.drop_duplicates(subset=['latitudeAcheteur', 'longitudeAcheteur'], keep='first')
df_HeatMap = df_HeatMap[df_HeatMap.populationAcheteur.notnull()]
df_HeatMap.reset_index(inplace=True, drop=True)
df_HeatMap['ratioMontantTTPopulation'] = df_HeatMap.montantTotal / df_HeatMap.populationAcheteur
df_HeatMap['ratioMontantTTPopulation'] = np.where(df_HeatMap['populationAcheteur']==0, 0, df_HeatMap['ratioMontantTTPopulation'])
df_HeatMap.ratioMontantTTPopulation = round(df_HeatMap.ratioMontantTTPopulation/10,0).astype(int)
df_HeatMap['ratioMontantTTPopulation'] = np.where(df_HeatMap['ratioMontantTTPopulation']>300, 300, df_HeatMap['ratioMontantTTPopulation'])

df_HeatMap2 = pd.DataFrame(columns=['latitudeAcheteur','longitudeAcheteur'])
df_HeatMap2.reset_index(inplace=True, drop = True)
l=0  
ran = [i for i in range(0,len(df_HeatMap),250)] + [len(df_HeatMap)]
for k in ran:
    df_temp2 = pd.DataFrame(columns=['latitudeAcheteur','longitudeAcheteur'])
    for i in range(l, k):
        print(i)
        for j in range(df_HeatMap.ratioMontantTTPopulation[i]):
            ar = np.array([[df_HeatMap.latitudeAcheteur[i],df_HeatMap.longitudeAcheteur[i]]])
            df_temp = pd.DataFrame(ar, columns = ['latitudeAcheteur', 'longitudeAcheteur'])
            df_temp2 = pd.concat([df_temp2, df_temp])
    df_HeatMap2 = pd.concat([df_HeatMap2, df_temp2])
    l=k
del l, i, j, k, ar, df_temp, df_temp2, ran  

base_map = folium.Map(location=[47, 2.0], zoom_start=6, max_zoom=12, min_zoom=5, tiles='OpenStreetMap')
HeatMap(data=df_HeatMap2[['latitudeAcheteur', 'longitudeAcheteur']], radius=8).add_to(base_map)
marker_cluster = MarkerCluster().add_to(base_map)
for i in range (len(df_carte)):
    folium.Marker([df_carte.latitudeAcheteur[i],  df_carte.longitudeAcheteur[i]], 
                  icon=folium.features.CustomIcon('https://images.emojiterra.com/google/android-nougat/512px/2753.png', icon_size=(10,10)),
                  popup = folium.Popup('<b>' + df_carte.libelleCommuneAcheteur[i] + '</b></br>'
                  + '<b>' + df_carte.nbMarches[i].astype(str) + '</b> marchés '
                  #+ 'Montant total des marchés : ' + df_carte.montantTotal[i].astype(str) + ' €' + '</br>'
                  +  " pour <b>" + df_carte.nbEntreprises[i].astype(str) + '</b> entreprises ',
                  max_width = 320, min_width = 200)  
                  , clustered_marker = True).add_to(marker_cluster)
base_map.save('carte/HeatMapDECP.html')

# Répartition des marchés
a = folium.Map(location=[47, 2.0], zoom_start=6, max_zoom=8, min_zoom=5, tiles='OpenStreetMap')
HeatMap(data=df_carte[['latitudeAcheteur', 'longitudeAcheteur']], radius=8).add_to(a)
a.save('carte/carteRépartitionDECP.html')
del df_HeatMap, df_HeatMap2, df_bar, i

###############################################################################
###############################################################################
### Récap des erreurs
df_ERROR = df_decp[(df_decp.montantEstEstime=='Oui') | (df_decp.dureeMoisEstEstime=='Oui') 
                    | (df_decp.geomAcheteur.isnull()) | (df_decp.geomEtablissement.isnull())]

df_ERROR = df_ERROR[['identifiantMarche','objetMarche', 'acheteurId','acheteurNom', 
                     'idEtablissement', 'montantOriginal',  'dureeMois',
                     'montantEstEstime', 'dureeMoisEstEstime', 'geomAcheteur', 'geomEtablissement']]
df_ERROR.columns = ['identifiantMarche','objetMarche', 'acheteurId','acheteurNom', 'EtablissementID',
                     'montantOriginal', 'dureeMoisOriginal', 'montantAberrant', 'dureeMoisAberrant',
                     'siretAcheteur', 'siretEtablissement']
df_ERROR.siretAcheteur = np.where(df_ERROR.siretAcheteur.isnull(), 'MAUVAIS', 'BON')
df_ERROR.siretEtablissement = np.where(df_ERROR.siretEtablissement.isnull(), 'MAUVAIS', 'BON')

df_Classement = pd.DataFrame.copy(df_ERROR, deep = True)
df_Classement = df_Classement[['acheteurNom', 'montantAberrant', 'dureeMoisAberrant', 'siretAcheteur', 'siretEtablissement']]
df_Classement.columns = ['acheteurNom', 'montantEstEstime', 'dureeMoisEstEstime', 'siretAcheteur', 'siretEtablissement']
df_Classement.montantEstEstime = np.where(df_Classement.montantEstEstime=='Oui',1,0)
df_Classement.dureeMoisEstEstime = np.where(df_Classement.dureeMoisEstEstime=='Oui',1,0)
df_Classement.siretAcheteur = np.where(df_Classement.siretAcheteur=='MAUVAIS',1,0)
df_Classement.siretEtablissement = np.where(df_Classement.siretEtablissement=='MAUVAIS',1,0)

df_Classement = df_Classement.groupby(['acheteurNom']).sum().reset_index()
df_50 = pd.DataFrame(df_Classement[(df_Classement.montantEstEstime >= 50) |
        (df_Classement.dureeMoisEstEstime >= 300) |
        (df_Classement.siretAcheteur >= 180) |
        (df_Classement.siretEtablissement >= 50)])
df_50['Note']=df_50.montantEstEstime*4+df_50.dureeMoisEstEstime*1+df_50.siretAcheteur*1+df_50.siretEtablissement*2
df_50=df_50.sort_values(by = 'Note', ascending = False)
del df_50['Note']

#siretEtablissement
Bilan=pd.DataFrame(df_Classement.sum()[1:5]).T; Bilan.columns=['Montant aberrant ','Durée en mois aberrante ','Siret acheteur mauvais ','Siret entreprise mauvais ']

# Les pires lignes (4 erreurs): 
F = df_ERROR[(df_ERROR.montantAberrant=='Oui') & (df_ERROR.dureeMoisAberrant=='Oui') & (df_ERROR.siretAcheteur=='MAUVAIS') & (df_ERROR.siretEtablissement=='MAUVAIS')]

# Liste de tous les acheteurs ayant fait au moins 10 supposées erreurs :
df_Classement['Total'] = df_Classement.montantEstEstime + df_Classement.dureeMoisEstEstime + df_Classement.siretAcheteur + df_Classement.siretEtablissement
ListeMauvaixAcheteurs = pd.DataFrame(np.array([df_Classement.acheteurNom[df_Classement['Total']>10].unique()]).T, columns=['Acheteur'])

###############################################################################
### Rapide aperçu des données principales
# Aperçu répartition des sources
round(df_decp.source.value_counts(normalize=True)*100,2) # pourcentage des sources
df_decp.source.value_counts(normalize=True).plot(kind='pie')

# Recapitulatif quantitatif
df_RECAP = pd.concat([df_decp.montantOriginal.describe(),
                      df_decp.montant.describe(),
                      df_decp.dureeMois.describe(),
                      df_decp.dureeMoisCalculee.describe(),
                      df_decp.distanceAcheteurEtablissement.describe()], axis=1)
df_RECAP.columns=['Montant original (€)', 'Montant calculé (€)', 'Durée en mois originale', 'Durée en mois calculée','Distance acheteur - établissement (km)']
df_RECAP = df_RECAP[1:8]

# Récupération sous format CSV
df_ERROR.to_csv(r'resultatsCSV/df_ERROR.csv', sep=';',index = False, header=True, encoding='utf-8')
ListeMauvaixAcheteurs.to_csv(r'resultatsCSV/ListeMauvaixAcheteurs.csv', sep=';',index = False, header=True, encoding='utf-8')
df_50.columns = ['acheteurNom', 'montantAberrant', 'dureeMoisAberrant', 'siretAcheteurFAUX', 'siretEtablissementFAUX']
df_50.to_csv(r'resultatsCSV/df_50.csv', sep=';',index = False, header=True, encoding='utf-8')

del F, ListeMauvaixAcheteurs, df_ERROR, df_RECAP, df_50, df_Classement, Bilan
#del df, df_carte

'''
###############################################################################
###############################################################################
###############################################################################
###############################################################################
###############################################################################

# Avant vérifier les formats avec Regex

'nature_DELEGATION DE SERVICE PUBLIC', 'nature_Délégation de service public'


# Exportation des données 
#df.dtypes
df.to_csv(r'decp.csv', sep=';',index = False, header=True, encoding='utf-8')
 
# Réimportation des données
df_decp = pd.read_csv('H:/Desktop/Data/decp.csv', sep=';', encoding='utf-8', 
                      dtype={'acheteurId' : str, 'nicEtablissement' : str, 'codeRegionAcheteur' : str, 'denominationSocialeEtablissement' : str,
                             'moisNotification' : str,  'idEtablissement' : str, 'montantOriginal' : float, 'montant' : float, 'montantTotalMarche' : float, 'codeDepartementAcheteur' : str,
                             'anneeNotification' : str, 'codeCommuneEtablissement' : str, 'codePostalEtablissement' : str,  'identifiantMarche' : str,
                             'codeTypeEtablissement' : str, 'sirenEtablissement' : str, 'siretEtablissement' : str, 'codeCPV' : str,
                             'nbTitulairesSurCeMarche' : int, 'dureeMois': int, 'dureeMoisCalculee': int, 'codeCommuneAcheteur': str, 'codePostalAcheteur': str})

#### Comparaison de toutes les autres colonnes
dftest = df.drop(columns=['formePrix', 'denominationSocialeEtablissement'])
dftest_copy = df.drop(columns=['formePrix' , 'denominationSocialeEtablissement'])
try:
    assert_frame_equal(dftest, dftest_copy)
    print(True)
except:
    print(False)
'''
